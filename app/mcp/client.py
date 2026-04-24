def retrieve_live_company_data(message: str, metadata: dict) -> str:
    """
    Placeholder for MCP integration.
    This intentionally returns deterministic data until real connectors are wired.
    """
    ticket_ref = metadata.get("ticket_ref", "unknown")
    return f"Live company data lookup completed for request '{message[:80]}' (ticket_ref={ticket_ref})."
