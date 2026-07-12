from Agent.tools import ToolRegistry

def setup_toolcalls(registry: ToolRegistry):
    from . import shell, temp_background_service, shell_kill, read, write, replace, remove, GetSymbolSourceCode, GetFileCodeStructure, document, walk_call_tree, list_dir, search, fuzzy_search, read_image, dispatch_subagent, todo_list, web_fetch, web_search, view_changes, ask_user, edit_symbol
    from skills.tool import handle as update_skill_handle
    from skills.tool import handle_get_skill as get_skill_handle

    registry.set_handler("UglyWholeFileContentDump", read.handle)
    registry.set_handler("SearchAllFilesContent", search.handle)
    registry.set_handler("FileNameSearch", fuzzy_search.handle)
    registry.set_handler("ListDir", list_dir.handle)
    registry.set_handler("WriteFile", write.handle)
    registry.set_handler("Shell", shell.handle)
    registry.set_handler("TempBackgroundService", temp_background_service.handle)
    registry.set_handler("ShellKill", shell_kill.handle)
    registry.set_handler("ReplaceText", replace.handle)
    registry.set_handler("RemoveFile", remove.handle)
    registry.set_handler("GetSymbolSourceCode", GetSymbolSourceCode.handle)
    registry.set_handler("GetFileCodeSemantics", GetFileCodeStructure.handle)
    registry.set_handler("WalkCallTree", walk_call_tree.handle)
    registry.set_handler("Document", document.handle)
    registry.set_handler("SetSkill", update_skill_handle)
    registry.set_handler("GetSkill", get_skill_handle)
    registry.set_handler("ReadImage", read_image.handle)
    registry.set_handler("WebFetch", web_fetch.handle)
    registry.set_handler("WebSearch", web_search.handle)
    registry.set_handler("DispatchSubagent", dispatch_subagent.handle)
    registry.set_handler("CreateTodoList", todo_list.handle_create_todo_list)
    registry.set_handler("AddTask", todo_list.handle_add_task)
    registry.set_handler("GetTodoList", todo_list.handle_get_todo_list)
    registry.set_handler("ApproveTodoList", todo_list.handle_approve_todo_list)
    registry.set_handler("ExecuteNextTask", todo_list.handle_execute_next_task)
    registry.set_handler("MarkTaskComplete", todo_list.handle_mark_task_complete)
    registry.set_handler("MarkTaskFailed", todo_list.handle_mark_task_failed)
    registry.set_handler("MarkTaskCancelled", todo_list.handle_mark_task_cancelled)
    registry.set_handler("GetActiveTodoList", todo_list.handle_get_active_todo_list)
    registry.set_handler("AskUser", ask_user.handle)
    registry.set_handler("ViewChanges", view_changes.handle)
    registry.set_handler("EditSymbol", edit_symbol.handle)
