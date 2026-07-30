def handle(args, agent):
    """Manually trigger re-indexing of the codebase.

    Usage:
      /reindex           Index new/changed files (incremental)
      /reindex --force   Force re-index all files from scratch
    """
    force = "--force" in args

    if agent.code_indexer is None:
        print("No code indexer available.")
        return ""

    try:
        if force:
            print("Force re-indexing all files...")
        else:
            print("Re-indexing changed files...")
        agent.code_indexer.index_directory(force_reindex=force)
        print("Indexing complete.")
    except (KeyboardInterrupt, EOFError):
        print("\nRe-indexing interrupted.")
        agent.code_indexer._connect()
    except Exception as e:
        print(f"Re-indexing failed: {e}")

    return ""
