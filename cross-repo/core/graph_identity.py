"""Unambiguous, repository-scoped graph identities."""
import json


def entity_id(*parts: str) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def dependency_type(name: str) -> str:
    markers = (
        'twilio', 'sendgrid', 'aws', 's3', 'sns', 'sqs', 'kafka', 'rabbitmq',
        'smtp', 'firebase', 'fcm', 'gcm', 'stripe', 'razorpay', 'sms',
    )
    return 'external_service' if any(marker in name.lower() for marker in markers) else 'missing_repo'
