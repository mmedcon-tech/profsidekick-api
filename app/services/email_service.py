import smtplib
import logging
import requests
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP, SendGrid, Resend, or Gmail API"""

    def __init__(self):
        self.email_service = settings.email_service.lower()

        # SMTP settings
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_username = settings.smtp_username
        self.smtp_password = settings.smtp_password
        self.from_email = settings.smtp_from_email
        self.from_name = settings.smtp_from_name

        # API keys
        self.sendgrid_api_key = settings.sendgrid_api_key
        self.resend_api_key = settings.resend_api_key

        logger.info(f"Email service initialized with provider: {self.email_service}")

    async def send_email(
        self,
        to_email: str | List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """
        Send an email using configured provider (SMTP, SendGrid, or Resend)

        Args:
            to_email: Recipient email address or list of addresses
            subject: Email subject
            html_content: HTML content of the email
            text_content: Plain text content (optional)

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if self.email_service == "sendgrid":
                return await self._send_via_sendgrid(
                    to_email, subject, html_content, text_content
                )
            elif self.email_service == "resend":
                return await self._send_via_resend(
                    to_email, subject, html_content, text_content
                )
            else:  # default to SMTP
                return await self._send_via_smtp(
                    to_email, subject, html_content, text_content
                )
        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            return False

    async def _send_via_sendgrid(
        self,
        to_email: str | List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Send email via SendGrid HTTP API"""
        try:
            to_emails = [to_email] if isinstance(to_email, str) else to_email

            payload = {
                "personalizations": [{"to": [{"email": email} for email in to_emails]}],
                "from": {"email": self.from_email, "name": self.from_name},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_content}],
            }

            if text_content:
                payload["content"].insert(
                    0, {"type": "text/plain", "value": text_content}
                )

            response = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {self.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
            logger.info(f"✅ Email sent via SendGrid to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ SendGrid API error: {e}")
            return False

    async def _send_via_resend(
        self,
        to_email: str | List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Send email via Resend HTTP API"""
        try:
            to_emails = [to_email] if isinstance(to_email, str) else to_email

            payload = {
                "from": f"{self.from_name} <{self.from_email}>",
                "to": to_emails,
                "subject": subject,
                "html": html_content,
            }

            if text_content:
                payload["text"] = text_content

            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
            logger.info(f"✅ Email sent via Resend to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Resend API error: {e}")
            return False

    async def _send_via_smtp(
        self,
        to_email: str | List[str],
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Send email via SMTP (for local development)"""
        try:
            logger.info(f"Sending email to {to_email} with subject {subject}")
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email if isinstance(to_email, str) else ", ".join(to_email)
            msg["Subject"] = subject

            # Add text and HTML parts
            if text_content:
                part1 = MIMEText(text_content, "plain")
                msg.attach(part1)

            part2 = MIMEText(html_content, "html")
            msg.attach(part2)

            # Send email
            logger.info(f"Sending email to {to_email} with subject {subject}")
            logger.info(f"SMTP host: {self.smtp_host}")
            logger.info(f"SMTP port: {self.smtp_port}")
            logger.info(f"SMTP username: {self.smtp_username}")
            logger.info(f"SMTP from email: {self.from_email}")
            logger.info(f"SMTP from name: {self.from_name}")
            # Use SMTP_SSL if port is 465, otherwise use SMTP with STARTTLS
            if self.smtp_port == 465:
                logger.info("Using SMTP_SSL (port 465)")
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)
            else:
                logger.info(f"Using SMTP with STARTTLS (port {self.smtp_port})")
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)

            logger.info(f"✅ Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            return False

    async def send_verification_email(
        self, to_email: str, user_name: str, verification_token: str
    ) -> bool:
        """
        Send email verification link

        Args:
            to_email: User's email address
            user_name: User's full name
            verification_token: Unique verification token

        Returns:
            True if email sent successfully
        """
        verification_url = (
            f"{settings.frontend_url}/verify-email?token={verification_token}"
        )

        subject = "Verify Your Email - ProfSidekick"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .content {{
                    background: #f9f9f9;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .button {{
                    display: inline-block;
                    padding: 15px 30px;
                    background: #667eea;
                    color: white !important;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Welcome to ProfSidekick! 🎓</h1>
            </div>
            <div class="content">
                <p>Hi {user_name},</p>
                
                <p>Thank you for registering with ProfSidekick! We're excited to have you on board.</p>
                
                <p>To complete your registration, please verify your email address by clicking the button below:</p>
                
                <center>
                    <a href="{verification_url}" class="button">Verify Email Address</a>
                </center>
                
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #667eea;">{verification_url}</p>
                
                <p><strong>Important:</strong> After verifying your email, your account will be sent for approval. You'll receive another email once your account is approved and ready to use.</p>
                
                <p>This link will expire in 24 hours for security reasons.</p>
                
                <div class="footer">
                    <p>If you didn't create an account with ProfSidekick, please ignore this email.</p>
                    <p>&copy; 2025 ProfSidekick. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Welcome to ProfSidekick!
        
        Hi {user_name},
        
        Thank you for registering with ProfSidekick! We're excited to have you on board.
        
        To complete your registration, please verify your email address by visiting:
        {verification_url}
        
        Important: After verifying your email, your account will be sent for approval. You'll receive another email once your account is approved and ready to use.
        
        This link will expire in 24 hours for security reasons.
        
        If you didn't create an account with ProfSidekick, please ignore this email.
        """

        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_approval_request_email(
        self, user_email: str, user_name: str, user_role: str, approval_token: str
    ) -> bool:
        """
        Send approval request to professor

        Args:
            user_email: New user's email
            user_name: New user's full name
            user_role: User's role (professor/student)
            approval_token: Unique approval token

        Returns:
            True if email sent successfully
        """
        approval_url = f"{settings.frontend_url}/approve-user?token={approval_token}"

        subject = f"New User Registration - Approval Required"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .content {{
                    background: #f9f9f9;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .user-info {{
                    background: white;
                    padding: 20px;
                    border-radius: 5px;
                    margin: 20px 0;
                    border-left: 4px solid #667eea;
                }}
                .button {{
                    display: inline-block;
                    padding: 15px 30px;
                    background: #10b981;
                    color: white !important;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>New User Registration</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                
                <p>A new user has registered on ProfSidekick and verified their email. Please review their information and approve their account:</p>
                
                <div class="user-info">
                    <p><strong>Name:</strong> {user_name}</p>
                    <p><strong>Email:</strong> {user_email}</p>
                    <p><strong>Role:</strong> {user_role.title()}</p>
                </div>
                
                <center>
                    <a href="{approval_url}" class="button">Approve Account</a>
                </center>
                
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #667eea;">{approval_url}</p>
                
                <p>Once approved, the user will receive an email notification and can start using the platform.</p>
                
                <div class="footer">
                    <p>&copy; 2025 ProfSidekick. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        New User Registration - Approval Required
        
        Hello,
        
        A new user has registered on ProfSidekick and verified their email. Please review their information and approve their account:
        
        Name: {user_name}
        Email: {user_email}
        Role: {user_role.title()}
        
        To approve this account, visit:
        {approval_url}
        
        Once approved, the user will receive an email notification and can start using the platform.
        """

        return await self.send_email(
            settings.professor_approval_emails, subject, html_content, text_content
        )

    async def send_approval_confirmation_email(
        self, to_email: str, user_name: str
    ) -> bool:
        """
        Send email to user after their account is approved

        Args:
            to_email: User's email address
            user_name: User's full name

        Returns:
            True if email sent successfully
        """
        login_url = f"{settings.frontend_url}/login"

        subject = "Your Account Has Been Approved! 🎉"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .content {{
                    background: #f9f9f9;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .button {{
                    display: inline-block;
                    padding: 15px 30px;
                    background: #667eea;
                    color: white !important;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Account Approved! 🎉</h1>
            </div>
            <div class="content">
                <p>Hi {user_name},</p>
                
                <p>Great news! Your ProfSidekick account has been approved and is now active.</p>
                
                <p>You can now log in and start using all the features of ProfSidekick:</p>
                
                <ul>
                    <li>Create and manage courses</li>
                    <li>Generate interactive teaching sessions</li>
                    <li>Upload and analyze presentation materials</li>
                    <li>And much more!</li>
                </ul>
                
                <center>
                    <a href="{login_url}" class="button">Log In Now</a>
                </center>
                
                <p>If you have any questions or need assistance, feel free to reach out to us.</p>
                
                <p>Welcome aboard!</p>
                
                <div class="footer">
                    <p>&copy; 2025 ProfSidekick. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Account Approved!
        
        Hi {user_name},
        
        Great news! Your ProfSidekick account has been approved and is now active.
        
        You can now log in and start using all the features of ProfSidekick:
        - Create and manage courses
        - Generate interactive teaching sessions
        - Upload and analyze presentation materials
        - And much more!
        
        Log in now at: {login_url}
        
        If you have any questions or need assistance, feel free to reach out to us.
        
        Welcome aboard!
        """

        return await self.send_email(to_email, subject, html_content, text_content)


# Global instance
email_service = EmailService()
