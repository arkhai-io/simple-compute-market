import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from src.db.models import Agent, HealthCheck
from src.db.database import SessionLocal
from src.config import settings
from src.db.models import AgentStatusEnum
import aiohttp

logger = logging.getLogger(__name__)


class HealthCheckService:
    def __init__(self):
        self.is_running = False
        self.check_task: Optional[asyncio.Task] = None

    async def start(self, interval_sec: int = 60):
        """Start the health check service"""
        if self.is_running:
            logger.info("[HealthCheck] Service already running")
            return

        self.is_running = True
        logger.info(f"[HealthCheck] Starting health check service (interval: {interval_sec}s)...")

        # Perform initial check
        await self.perform_health_checks()

        # Set up periodic checks
        self.check_task = asyncio.create_task(self._periodic_check(interval_sec))

    async def stop(self):
        """Stop the health check service"""
        if not self.is_running:
            return

        self.is_running = False
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass
        logger.info("[HealthCheck] Health check service stopped")

    async def _periodic_check(self, interval_sec: int):
        """Periodic health check loop"""
        while self.is_running:
            try:
                await asyncio.sleep(interval_sec)
                await self.perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HealthCheck] Error during health check: {e}")

    async def perform_health_checks(self):
        """Perform health checks on all agents"""
        db = SessionLocal()
        try:
            agents = db.query(Agent).all()
            logger.info(f"[HealthCheck] Checking {len(agents)} agents...")

            now = datetime.utcnow()
            checks = await asyncio.gather(
                *[self._check_agent(agent, now, db) for agent in agents],
                return_exceptions=True
            )

            failed = sum(1 for c in checks if isinstance(c, Exception))
            if failed > 0:
                logger.warning(f"[HealthCheck] {failed} health checks failed")

            logger.info("[HealthCheck] Health checks completed")
        finally:
            db.close()

    async def _check_agent(self, agent: Agent, now: datetime, db: Session):
        """Check a single agent"""
        try:
            # Check heartbeat status
            status = AgentStatusEnum.healthy

            if agent.last_heartbeat:
                heartbeat_age = (now - agent.last_heartbeat).total_seconds()

                if heartbeat_age > settings.heartbeat_ttl_secs:
                    # Heartbeat is stale, check endpoint
                    endpoint_status = await self.check_endpoint(
                        agent.metadata_json.get("url") if agent.metadata_json else None or agent.token_uri
                    )

                    if endpoint_status["reachable"]:
                        status = AgentStatusEnum.stale
                    else:
                        status = AgentStatusEnum.unreachable
            else:
                # No heartbeat, check endpoint
                endpoint_status = await self.check_endpoint(
                    agent.metadata.get("url") if agent.metadata else None or agent.token_uri
                )
                status = AgentStatusEnum.stale if endpoint_status["reachable"] else AgentStatusEnum.unreachable

            # Update agent status if changed
            if agent.health_status != status.value:
                agent.health_status = status
                agent.updated_at = now
                db.commit()
                logger.info(f"[HealthCheck] Agent {agent.agent_id} status: {agent.health_status} → {status.value}")

            # Record health check
            endpoint_status = await self.check_endpoint(
                agent.metadata.get("url") if agent.metadata else None or agent.token_uri
            )
            health_check = HealthCheck(
                agent_id=agent.agent_id,
                status=status.value,
                response_time=endpoint_status.get("response_time"),
                error=endpoint_status.get("error"),
            )
            db.add(health_check)
            db.commit()
        except Exception as e:
            logger.error(f"[HealthCheck] Error checking agent {agent.agent_id}: {e}")
            db.rollback()

    async def check_endpoint(self, url: Optional[str]) -> dict:
        """Check if an agent endpoint is reachable"""
        if not url or not url.startswith("http"):
            return {"reachable": False, "error": "Invalid URL"}

        start_time = datetime.utcnow()

        try:
            timeout = aiohttp.ClientTimeout(total=settings.endpoint_check_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"User-Agent": "ERC-8004-Registry-HealthCheck/1.0"}) as response:
                    response_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    return {
                        "reachable": response.status < 500,
                        "response_time": response_time,
                    }
        except Exception as e:
            response_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return {
                "reachable": False,
                "response_time": response_time,
                "error": str(e),
            }

    async def check(self):
        """Manually trigger health checks"""
        await self.perform_health_checks()

    async def check_agent(self, agent_id: str) -> dict:
        """Check a specific agent"""
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
            if not agent:
                raise ValueError("Agent not found")

            endpoint_status = await self.check_endpoint(
                agent.metadata.get("url") if agent.metadata else None or agent.token_uri
            )

            status = AgentStatusEnum.healthy
            if not agent.last_heartbeat:
                status = AgentStatusEnum.stale if endpoint_status["reachable"] else AgentStatusEnum.unreachable
            else:
                heartbeat_age = (datetime.utcnow() - agent.last_heartbeat).total_seconds()
                if heartbeat_age > settings.heartbeat_ttl_secs:
                    status = AgentStatusEnum.stale if endpoint_status["reachable"] else AgentStatusEnum.unreachable

            agent.health_status = status
            agent.updated_at = datetime.utcnow()
            db.commit()

            health_check = HealthCheck(
                agent_id=agent_id,
                status=status.value,
                response_time=endpoint_status.get("response_time"),
                error=endpoint_status.get("error"),
            )
            db.add(health_check)
            db.commit()

            return {
                "agent_id": agent_id,
                "status": status.value,
                "endpoint_reachable": endpoint_status["reachable"],
                "response_time": endpoint_status.get("response_time"),
                "error": endpoint_status.get("error"),
            }
        finally:
            db.close()

