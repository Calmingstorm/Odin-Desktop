"""Conversation delivery constants; the durable sink is Phase 2-gated.

No transport facade or successful publication receipt is fabricated.
"""

CONVERSATION_MAX_LEN = 2000

TOOL_STATUS_LABELS: dict[str, str] = {
    "run_command": "Running a command",
    "run_script": "Executing a script",
    "run_command_multi": "Commanding multiple hosts",
    "read_file": "Reading a file",
    "apply_patch": "Applying a patch",
    "generate_file": "Forging an artifact",
    "post_file": "Delivering a file",
    "analyze_image": "Staring at a picture",
    "analyze_pdf": "Suffering through a PDF",
    "web_search": "Googling it like a mortal",
    "fetch_url": "Fetching a URL",
    "http_probe": "Checking a pulse",
    "browser_read_page": "Reading a webpage",
    "browser_screenshot": "Screenshotting a page",
    "browser_read_table": "Parsing a table",
    "browser_click": "Clicking things",
    "browser_fill": "Filling out a form",
    "browser_evaluate": "Running browser JS",
    "manage_process": "Babysitting a process",
    "validate_action": "Checking if it's still alive",
    "schedule_task": "Scheduling a future problem",
    "list_schedules": "Reviewing pending regrets",
    "update_schedule": "Adjusting the timeline",
    "delete_schedule": "Cancelling a fate",
    "start_loop": "Starting a watch",
    "stop_loop": "Ending a watch",
    "list_loops": "Checking active watches",
    "parse_time": "Deciphering mortal time",
    "spawn_agent": "Delegating the suffering",
    "wait_for_agents": "Waiting on subordinates",
    "get_agent_results": "Collecting the findings",
    "list_agents": "Checking on the crew",
    "kill_agent": "Terminating a subordinate",
    "delegate_task": "Handing off work",
    "list_tasks": "Reviewing the queue",
    "cancel_task": "Killing a task",
    "send_to_agent": "Messaging a subordinate",
    "memory_manage": "Remembering, reluctantly",
    "search_audit": "Reviewing the audit log",
    "search_history": "Digging through history",
    "search_knowledge": "Consulting the knowledge base",
    "ingest_document": "Ingesting a document",
    "bulk_ingest_knowledge": "Bulk ingesting documents",
    "list_knowledge": "Listing known documents",
    "delete_knowledge": "Forgetting on purpose",
    "create_skill": "Teaching myself a new trick",
    "edit_skill": "Refining a skill",
    "delete_skill": "Unlearning",
    "list_skills": "Listing skills",
    "enable_skill": "Enabling a skill",
    "disable_skill": "Shelving a skill",
    "invoke_skill": "Running a skill",
    "install_skill": "Installing a skill",
    "export_skill": "Exporting a skill",
    "skill_status": "Checking a skill",
    "read_conversation": "Reading the conversation",
    "generate_image": "Bothering the GPU",
    "manage_list": "Managing a list",
}


class DeliveryService:
    """No operational delivery until task-owned durable publication is wired."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Durable conversation delivery is deferred to Phase 2")
