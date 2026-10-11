"""
Voice Platform — Email Integration Client
============================================

Sends emails via SMTP during or after calls.

Use cases:
    - Send call summary to sales team
    - Email appointment confirmation to caller
    - Forward transcript to manager
    - Send follow-up information

Supports standard SMTP (Gmail, Outlook, SendGrid, custom SMTP).
"""

import asyncio
import base64
import email.mime.multipart
import email.mime.text
import mimetypes
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from typing import Any, List, Optional

from loguru import logger


class EmailClient:
    """
    SMTP email client for sending emails from workflows.
    
    Config:
        smtp_host: SMTP server hostname (e.g. smtp.gmail.com)
        smtp_port: SMTP port (587 for TLS, 465 for SSL)
        smtp_user: SMTP username/email
        from_email: Sender email address (defaults to smtp_user)
        from_name: Sender display name (e.g. "VOIA Platform")
        use_tls: Whether to use STARTTLS (default: True)
    
    API Key: SMTP password or app-specific password
    """
    
    def __init__(self, api_key: str, config: dict = None):
        self._password = api_key
        self._config = config or {}
        self._host = self._config.get("smtp_host", "smtp.gmail.com")
        self._port = int(self._config.get("smtp_port", 587))
        self._user = self._config.get("smtp_user", "")
        self._from_email = self._config.get("from_email", self._user)
        self._from_name = self._config.get("from_name", "VOIA Platform")
        self._use_tls = self._config.get("use_tls", True)
    
    async def test_connection(self) -> dict:
        """
        Verify SMTP connectivity and credentials without sending an email.
        Returns success dict or raises ConnectionError on failure.
        """
        import asyncio

        def _test():
            if self._use_tls:
                server = smtplib.SMTP(self._host, self._port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self._host, self._port, timeout=10)
            server.login(self._user, self._password)
            server.quit()

        try:
            await asyncio.to_thread(_test)
            return {"success": True, "host": self._host, "port": self._port}
        except Exception as e:
            logger.error(f"SMTP test failed for {self._host}:{self._port}: {e}")
            raise ConnectionError(f"SMTP connection failed: {e}")

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        cc: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> dict:
        """
        Send an email via SMTP.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain text body
            html_body: Optional HTML body (for rich formatting)
            cc: Optional CC recipients (comma-separated)
            attachments: Optional list of attachment dicts, each with:
                - filename: str (required)
                - content: bytes or base64-encoded str (required)
                - mime_type: str (optional, auto-detected from filename)

        Returns:
            dict with success status and details
        """
        if not to:
            return {"success": False, "error": "Recipient email address is required", "to": to}
        if not subject:
            subject = "VOIA Platform Notification"

        def _send():
            msg = email.mime.multipart.MIMEMultipart("mixed")
            msg["From"] = f"{self._from_name} <{self._from_email}>"
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc

            # Body part (alternative text + html)
            body_part = email.mime.multipart.MIMEMultipart("alternative")
            body_part.attach(email.mime.text.MIMEText(body, "plain"))
            if html_body:
                body_part.attach(email.mime.text.MIMEText(html_body, "html"))
            msg.attach(body_part)

            # Attach files
            if attachments:
                for att in attachments:
                    filename = att.get("filename", "attachment")
                    content = att.get("content")
                    mime_type = att.get("mime_type")

                    if not content:
                        continue

                    # Decode base64 if string
                    if isinstance(content, str):
                        try:
                            content = base64.b64decode(content)
                        except Exception:
                            content = content.encode("utf-8")

                    # Auto-detect MIME type
                    if not mime_type:
                        mime_type, _ = mimetypes.guess_type(filename)
                        mime_type = mime_type or "application/octet-stream"

                    main_type, sub_type = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")

                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(content)
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{filename}"',
                    )
                    msg.attach(part)

            # Connect and send
            if self._use_tls:
                server = smtplib.SMTP(self._host, self._port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self._host, self._port, timeout=10)

            server.login(self._user, self._password)

            recipients = [to]
            if cc:
                recipients.extend([addr.strip() for addr in cc.split(",")])

            server.sendmail(self._from_email, recipients, msg.as_string())
            server.quit()

            return {
                "success": True,
                "to": to,
                "subject": subject,
                "cc": cc,
                "attachments_count": len(attachments) if attachments else 0,
            }
        
        try:
            result = await asyncio.to_thread(_send)
            logger.info(f"📧 Email sent to {to}: {subject}")
            return result
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to,
            }

