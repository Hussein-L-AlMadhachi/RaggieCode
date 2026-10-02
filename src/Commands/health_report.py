def handle(args, agent):
    """Generate a full code complexity report and save it to a .txt file.

    Usage:
      /health
    """
    if agent.code_indexer is None or agent.code_indexer.conn is None:
        print("No code index available. Run /reindex first.")
        return ""

    report_path = agent._write_full_complexity_report()
    if report_path:
        print(f"Complexity report saved to: {report_path}")
    else:
        print("No complex functions found or report generation failed.")

    return ""
