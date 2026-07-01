from __future__ import annotations
"""CLI dispatcher — argparse root with --json, --adapter, command routing."""

import argparse
import json
import sys
from typing import Any

from memory_cli.core.config import load_config
from memory_cli.commands import status, ingest, consolidate, recall, inbox as inbox_cmd, parse as parse_cmd, doctor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory",
        description="Unified memory management CLI for pi coding agent.",
    )
    
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (for programmatic use)")
    parser.add_argument("--adapter", choices=["file", "graph", "search", "all"],
                        default="all", help="Which adapters to use (default: all)")
    parser.add_argument("--verbose", action="store_true",
                        help="Extra diagnostic output to stderr")
    parser.add_argument("--config", help="Override config.json path")
    
    sub = parser.add_subparsers(dest="command", required=True)
    
    # status
    p_status = sub.add_parser("status", help="Memory system observability and health")
    p_status.add_argument("--health", action="store_true",
                          help="Health check (exit code 1 if issues)")
    
    # ingest
    p_ingest = sub.add_parser("ingest", help="Capture memory from input")
    p_ingest.add_argument("text", nargs="*", help="Text to capture")
    p_ingest.add_argument("--stdin", action="store_true",
                          help="Read from stdin")
    p_ingest.add_argument("--file", help="Read from file")
    p_ingest.add_argument("--target", choices=["global", "project"],
                          help="Target scope (default: auto-detect)")
    p_ingest.add_argument("--section",
                          choices=["learning", "gotcha", "preference", "decision",
                                   "rule", "convention", "architecture", "workflow",
                                   "project-fact"],
                          help="Section for direct mode (maps to section header)")
    p_ingest.add_argument("--dry-run", action="store_true",
                          help="Preview without writing")
    p_ingest.add_argument("--no-dedup", action="store_true",
                          help="Skip semantic dedup check")
    p_ingest.add_argument("--direct", action="store_true",
                          help="Write content directly without trigger/pattern matching")
    p_ingest.add_argument("--no-index", action="store_true",
                          help="Skip FTS5 index auto-rebuild (faster batch ingest)")
    
    # consolidate
    p_cons = sub.add_parser("consolidate", help="LLM consolidation of session transcript")
    p_cons.add_argument("--source", choices=["pi", "factory"],
                        help="Session source harness")
    p_cons.add_argument("--session", help="Session ID")
    p_cons.add_argument("--transcript", help="Path to transcript file (factory mode)")
    p_cons.add_argument("--dry-run", action="store_true",
                        help="Preview without writing")
    p_cons.add_argument("--no-llm", action="store_true",
                        help="Skip LLM (rule-based only)")
    p_cons.add_argument("--model", help="Override LLM model")
    
    # recall
    p_recall = sub.add_parser("recall", help="Search memory entries")
    p_recall.add_argument("query", nargs="?", help="Search query")
    p_recall.add_argument("--limit", type=int, default=20,
                          help="Max results")
    p_recall.add_argument("--context", type=int, default=0,
                          help="Lines of context around matches")
    p_recall.add_argument("--section", help="Filter by section")
    p_recall.add_argument("--no-hybrid", action="store_true",
                          help="Disable hybrid search (grep-only fallback)")
    p_recall.add_argument("--hybrid", action="store_true",
                          help=argparse.SUPPRESS)  # deprecated, now default
    
    # forget
    p_forget = sub.add_parser("forget", help="Delete memory entries")
    p_forget.add_argument("query", help="Entry content to match")
    p_forget.add_argument("--apply", action="store_true",
                          help="Actually delete (default: dry-run)")
    
    # index
    p_index = sub.add_parser("index", help="Rebuild archive tiers and/or search index")
    p_index.add_argument("--dry-run", action="store_true",
                         help="Preview tier changes (archive mode only)")
    p_index.add_argument("--search", dest="search_rebuild", action="store_true",
                         help="Rebuild search index from canonical entries")
    p_index.add_argument("--archive", action="store_true",
                         help="Rebuild hot/warm/cold archive tiers")
    p_index.add_argument("--rebuild", action="store_true", dest="search_rebuild",
                         help="Alias for --search")
    
    # inbox
    p_inbox = sub.add_parser("inbox", help="List/process compaction inbox")
    p_inbox.add_argument("--process", action="store_true",
                         help="Process pending inbox items")
    p_inbox.add_argument("--all", dest="all_files", action="store_true",
                         help="Process all pending items")
    p_inbox.add_argument("--file", help="Process specific file in inbox")
    p_inbox.add_argument("--consolidate", action="store_true",
                         help="Run LLM consolidation after processing")
    p_inbox.add_argument("--no-llm", action="store_true",
                         help="Rule-based extraction only")
    p_inbox.add_argument("--model", help="Override LLM model")
    
    # parse
    p_parse = sub.add_parser("parse", help="Parse memories.md into canonical entries")
    p_parse.add_argument("--validate", action="store_true",
                         help="Run validation checks")
    p_parse.add_argument("--verbose", action="store_true",
                         help="Show full entry details")
    
    # doctor
    p_doctor = sub.add_parser("doctor", help="Deep diagnostics and repair")
    p_doctor.add_argument("--repair", action="store_true",
                          help="Attempt to repair fixable issues")
    
    return parser


def _format_output(data: Any, json_mode: bool) -> str:
    """Format output as JSON or human-readable."""
    if json_mode:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return str(data)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    
    config = load_config(args.config)
    json_mode = args.json
    adapter_names = [] if args.adapter == "all" else [args.adapter]
    
    try:
        if args.command == "status":
            result = status.run(config=config, adapters=adapter_names,
                                health=args.health, verbose=args.verbose)
        elif args.command == "ingest":
            result = ingest.run(config=config, adapters=adapter_names,
                                text=args.text, stdin=args.stdin,
                                file=args.file, target=args.target,
                                dry_run=args.dry_run, no_dedup=args.no_dedup,
                                direct=args.direct, no_index=args.no_index,
                                section=args.section,
                                verbose=args.verbose)
        elif args.command == "consolidate":
            result = consolidate.run(config=config, adapters=adapter_names,
                                     source=args.source, session=args.session,
                                     transcript=args.transcript,
                                     dry_run=args.dry_run, no_llm=args.no_llm,
                                     model=args.model, verbose=args.verbose)
        elif args.command == "recall":
            result = recall.run(config=config, adapters=adapter_names,
                                query=args.query, limit=args.limit,
                                context=args.context, section=args.section,
                                hybrid=not args.no_hybrid,
                                verbose=args.verbose)
        elif args.command == "forget":
            from memory_cli.commands import forget
            result = forget.run(config=config, adapters=adapter_names,
                                query=args.query, apply=args.apply,
                                verbose=args.verbose)
        elif args.command == "index":
            from memory_cli.commands import index
            result = index.run(config=config, adapters=adapter_names,
                               dry_run=args.dry_run,
                               search_rebuild=args.search_rebuild,
                               archive=args.archive,
                               verbose=args.verbose)
        elif args.command == "inbox":
            result = inbox_cmd.run(config=config, adapters=adapter_names,
                                   process=args.process, all_files=args.all_files,
                                   file=args.file, consolidate=args.consolidate,
                                   no_llm=args.no_llm, model=args.model,
                                   verbose=args.verbose)
        elif args.command == "parse":
            result = parse_cmd.run(config=config, adapters=adapter_names,
                                   validate=args.validate, verbose=args.verbose)
        elif args.command == "doctor":
            result = doctor.run(config=config, repair=args.repair,
                                verbose=args.verbose)
        else:
            parser.print_help()
            return 1
        
        print(_format_output(result, json_mode))
        return 0 if result.get("status") in ("ok", "dry_run", "no_match") else 1
    
    except Exception as e:
        msg = {"command": args.command, "status": "error", "error": str(e)}
        print(_format_output(msg, json_mode), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
