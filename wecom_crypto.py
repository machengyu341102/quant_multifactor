"""
企业微信消息加解密 (回调验证用)
==============================
实现 WXBizMsgCrypt 用于:
  1. 验证回调 URL (VerifyURL)
  2. 解密/加密消息 (暂不需要)

参考: https://developer.work.weixin.qq.com/document/path/90930
"""

import base64
import hashlib
import struct
import socket
import time

from Crypto.Cipher import AES


class PKCS7Encoder:
    block_size = 32

    @staticmethod
    def encode(text: bytes) -> bytes:
        length = len(text)
        padding = PKCS7Encoder.block_size - (length % PKCS7Encoder.block_size)
        return text + bytes([padding] * padding)

    @staticmethod
    def decode(text: bytes) -> bytes:
        pad = text[-1]
        if pad < 1 or pad > PKCS7Encoder.block_size:
            return text
        return text[:-pad]


class WXBizMsgCrypt:
    """企业微信加解密"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.key = base64.b64decode(encoding_aes_key + "=")
        assert len(self.key) == 32

    def _sign(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """计算签名"""
        items = sorted([self.token, timestamp, nonce, encrypt])
        sig = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
        import logging
        logging.getLogger("wecom_crypto").warning(
            f"[签名] token={self.token}, echostr_len={len(encrypt)}, computed={sig}"
        )
        return sig

    def _decrypt(self, encrypted: str) -> tuple[int, str]:
        """AES 解密"""
        try:
            cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
            decrypted = cipher.decrypt(base64.b64decode(encrypted))
            plaintext = PKCS7Encoder.decode(decrypted)
            # 去掉 16 字节随机串 + 4 字节长度
            content_len = struct.unpack("!I", plaintext[16:20])[0]
            content = plaintext[20:20 + content_len].decode("utf-8")
            from_corp = plaintext[20 + content_len:].decode("utf-8")
            if from_corp != self.corp_id:
                return -1, ""
            return 0, content
        except Exception as e:
            return -1, str(e)

    def VerifyURL(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> tuple[int, str]:
        """验证回调 URL — 解密 echostr 并返回明文"""
        sign = self._sign(timestamp, nonce, echostr)
        if sign != msg_signature:
            return -1, "签名不匹配"
        ret, reply = self._decrypt(echostr)
        return ret, reply

    def DecryptMsg(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> tuple[int, str]:
        """解密收到的消息"""
        sign = self._sign(timestamp, nonce, encrypt)
        if sign != msg_signature:
            return -1, "签名不匹配"
        return self._decrypt(encrypt)

    def _encrypt(self, reply: str) -> str:
        """AES 加密"""
        import os
        reply_bytes = reply.encode("utf-8")
        corp_bytes = self.corp_id.encode("utf-8")
        body = os.urandom(16) + struct.pack("!I", len(reply_bytes)) + reply_bytes + corp_bytes
        body_padded = PKCS7Encoder.encode(body)
        cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
        return base64.b64encode(cipher.encrypt(body_padded)).decode()

    def EncryptMsg(self, reply: str, nonce: str) -> tuple[str, str]:
        """加密回复消息, 返回 (encrypt, signature)"""
        encrypt = self._encrypt(reply)
        ts = str(int(time.time()))
        sign = self._sign(ts, nonce, encrypt)
        return encrypt, sign, ts
