"""Notifications on your phone (Web Push). On an iPhone they work once Shortlist is added to the home screen (iOS 16.4 or newer)."""

import base64
import json
import threading

from . import db


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Pusher:
    def __init__(self, con, subject=lambda: "", send=None):
        self.con, self.subject = con, subject
        self._send = send  # a stand in for pywebpush.webpush in tests
        self._vapid = None
        self.sent = []

    def vapid(self):
        # One key pair per installation, made on first use and kept in the database.
        if self._vapid is None:
            from cryptography.hazmat.primitives import serialization
            from py_vapid import Vapid
            pem = db.get_setting(self.con, "vapid_private")
            if pem:
                v = Vapid.from_pem(pem.encode())
            else:
                v = Vapid()
                v.generate_keys()
                db.set_setting(self.con, "vapid_private", v.private_pem().decode())
            raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            self._vapid = (v, _b64(raw))
        return self._vapid

    @property
    def public_key(self):
        try:
            return self.vapid()[1]
        except Exception:  # pywebpush not installed: the app works, only without notifications
            return ""

    def notify(self, title, body, url="/", user_ids=None, role=None, tag=None, wait=False):
        targets = db.push_targets(self.con, user_ids=user_ids, role=role)
        if not targets:
            return 0
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or url})
        t = threading.Thread(target=self._deliver, args=(targets, payload), daemon=True)
        t.start()
        if wait:
            t.join()
        return len(targets)

    def _deliver(self, targets, payload):
        send = self._send
        if send is None:
            from pywebpush import webpush as send
        sub = self.subject() or "mailto:shortlist@users.noreply.github.com"
        for t in targets:
            info = {"endpoint": t["endpoint"], "keys": {"p256dh": t["p256dh"], "auth": t["auth"]}}
            try:
                send(info, data=payload, vapid_private_key=self.vapid()[0], vapid_claims={"sub": sub}, ttl=24 * 3600, timeout=10)
                self.sent.append((t["user_id"], payload))
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):  # the phone unsubscribed or the app was removed
                    db.drop_push(self.con, t["endpoint"])
