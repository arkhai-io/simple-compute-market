"""Logging configuration for the agent.

Cloud Run compatible: Detects Cloud Run environment and uses stdout/stderr
(which Cloud Logging automatically captures) instead of file logging.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def is_cloud_run() -> bool:
    """Detect if running in Google Cloud Run.
    
    Cloud Run sets K_SERVICE and K_REVISION environment variables.
    """
    return bool(os.getenv("K_SERVICE") or os.getenv("K_REVISION"))


def setup_file_logging(log_file_path: str | None = None, log_level: str = "INFO") -> None:
    """Configure logging for the agent.
    
    In Cloud Run: Uses stdout/stderr (captured by Cloud Logging)
    Locally: Uses file-based logging with rotation
    
    Args:
        log_file_path: Path to log file. If None, uses default location (local only).
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Check if running in Cloud Run
    if is_cloud_run():
        # Cloud Run: Use stdout/stderr only (Cloud Logging captures these automatically)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)
        
        logging.info(f"Logging configured for Cloud Run: stdout/stderr (captured by Cloud Logging), level={log_level}")
    else:
        # Local development: Use file-based logging
        # Default log file location
        if log_file_path is None:
            # Use agent_id from config helper for consistency
            try:
                from .config import get_agent_id
                agent_id = get_agent_id()
            except (ImportError, ValueError):
                # Fallback if config not available or validation fails
                agent_id = os.getenv("AGENT_ID", "root_agent")
            # Sanitize agent_id for filename (remove invalid chars, but should already be valid)
            safe_agent_id = "".join(c if c.isalnum() or c == '_' else '_' for c in agent_id)
            log_file_path = f"{safe_agent_id}.log"
        
        # Ensure log directory exists
        log_path = Path(log_file_path)
        log_dir = log_path.parent
        if log_dir != Path('.'):
            log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create rotating file handler (10MB per file, keep 5 backups)
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)
        
        # Also add console handler for immediate feedback
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)
        
        logging.info(f"Logging configured: file={log_file_path}, level={log_level}")

