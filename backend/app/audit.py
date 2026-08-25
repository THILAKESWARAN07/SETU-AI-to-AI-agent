import logging
from sqlalchemy.orm import Session
from backend.app.models import AuditEvent
from typing import Dict, Any, Optional

logger = logging.getLogger("setu.audit")

class AuditEngine:
    @staticmethod
    def log_event(
        db: Session,
        actor: str,
        action: str,
        result: str,
        reason: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        policy_version: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        """
        Records an audit event to the database.
        
        Args:
            db: SQLAlchemy Session.
            actor: Actor category (LLM, BUYER_AGENT, MERCHANT_AGENT, HUMAN, WEBHOOK, SYSTEM).
            action: Action identifier (e.g. EVALUATE_POLICY, PAY_ORDER, ATTACK_TEST).
            result: Result status (e.g. SUCCESS, BLOCKED, REQUIRES_APPROVAL, ERROR).
            reason: Optional explanation.
            entity_type: Affected entity name.
            entity_id: Affected entity ID.
            policy_version: Active merchant policy version.
            metadata: Custom key-value metadata dictionary.
        """
        event = AuditEvent(
            actor=actor,
            action=action,
            reason=reason,
            result=result,
            entity_type=entity_type,
            entity_id=entity_id,
            policy_version=policy_version,
            event_metadata=metadata or {}
        )
        db.add(event)
        try:
            db.commit()
            db.refresh(event)
            # Standard python console logging as well
            logger.info(
                f"[AUDIT] Actor: {actor} | Action: {action} | Result: {result} | Entity: {entity_type}:{entity_id} | Policy: {policy_version} | Reason: {reason}"
            )
            return event
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to write audit log: {e}")
            raise e
