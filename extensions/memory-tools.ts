/**
 * Memento — persistent memory for the Pi coding agent.
 *
 * Integrates the local-first memory CLI (~/.agent-memory) into Pi:
 *   - LLM tools: memory_recall, memory_remember, memory_status
 *   - Slash commands: /memory-status, /memory-recall, /memory-index, /memory-inbox
 *   - Auto-recall: before_agent_start hook (disabled during pi --print)
 *   - Session shutdown: consolidates learnings on quit
 *
 * Installation:
 *   See ~/.agent-memory/INSTALL.md or github.com/themuuln/memento
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { homedir } from "node:os";

// ── Configuration ────────────────────────────────────────────────

const MEMORY_CLI = process.env.MEMORY_CLI || "memory";
const HOME = homedir();
const AGENT_MEMORY_DIR =
	process.env.AGENT_MEMORY_DIR || `${HOME}/.agent-memory`;
const MAX_RECALL_RESULTS = 5;
const RECALL_CACHE_TTL = 10_000; // 10 seconds
const SEARCH_TIMEOUT = 10_000; // 10 seconds (sync calls)
const ASYNC_TIMEOUT = 5_000; // 5 seconds (auto-recall, non-blocking)

// ── Async memory CLI call ────────────────────────────────────────

function cliAsync(
	args: string[],
	stdin?: string,
	timeout = ASYNC_TIMEOUT,
): Promise<Record<string, unknown>> {
	return new Promise((resolve) => {
		const fullArgs = ["--json", ...args];
		const child = execFile(
			MEMORY_CLI,
			fullArgs,
			{
				encoding: "utf-8",
				timeout,
				env: { ...process.env, AGENT_MEMORY_DIR },
			},
			(_err, stdout) => {
				if (stdout) {
					try {
						resolve(JSON.parse(stdout) as Record<string, unknown>);
					} catch {
						resolve({});
					}
				} else {
					resolve({});
				}
			},
		);
		if (stdin && child.stdin) {
			child.stdin.write(stdin);
			child.stdin.end();
		}
	});
}

/** Format results snippet for tool output. */
function formatResults(
	results: Array<Record<string, unknown>>,
	max: number,
): string {
	if (!results || results.length === 0) return "No results found.";
	const lines: string[] = [`Found ${results.length} memory result(s):\n`];
	for (const r of results.slice(0, max)) {
		const content = String(r.content || "").slice(0, 300);
		const sources = Array.isArray(r._matched_sources)
			? r._matched_sources.join("+")
			: r.source || "memory";
		const score =
			r.score !== undefined ? ` (score: ${Number(r.score).toFixed(3)})` : "";
		lines.push(`• [${sources}]${score} ${content}`);
	}
	if (results.length > max) lines.push(`\n… and ${results.length - max} more`);
	return lines.join("\n");
}

// ── Dedup helper: skip near-identical entries ──
// Computes word-level Jaccard similarity between two strings.
function jaccardSimilarity(a: string, b: string): number {
	const setA = new Set(a.toLowerCase().split(/\s+/).filter(Boolean));
	const setB = new Set(b.toLowerCase().split(/\s+/).filter(Boolean));
	if (setA.size === 0 && setB.size === 0) return 1;
	const intersect = new Set([...setA].filter((w) => setB.has(w)));
	const union = new Set([...setA, ...setB]);
	return intersect.size / union.size;
}

// Filter results to skip entries too similar to already-selected ones.
function dedupResults(
	results: Array<Record<string, unknown>>,
	threshold = 0.6,
): Array<Record<string, unknown>> {
	const deduped: Array<Record<string, unknown>> = [];
	for (const r of results) {
		const c = String(r.content || "");
		const isDuplicate = deduped.some(
			(existing) => jaccardSimilarity(c, String(existing.content || "")) >= threshold,
		);
		if (!isDuplicate) deduped.push(r);
	}
	return deduped;
}

// ── Cache ────────────────────────────────────────────────────────

let lastRecallQuery: string | null = null;
let cachedRecall: string | null = null;
let lastRecallTime = 0;

// ── Extension Entry Point ────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	// ── Footer status badge (no-op with pi-minimal-footer) ──
	// Feedback is available via /memory-status slash command and memory_status tool.
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	function updateFooter(..._args: any[]) {
		// No-op: user's custom footer extension doesn't render status keys.
	}

	// ── LLM Tool: memory_recall ──
	pi.registerTool({
		name: "memory_recall",
		label: "Memory Recall",
		description:
			"Search persistent memories from past sessions for context about a topic. " +
			"Returns relevant entries from past decisions, preferences, learnings, and gotchas.",
		promptSnippet:
			"Search persistent memories (past sessions, decisions, preferences)",
		promptGuidelines: [
			"Use memory_recall proactively when starting work to check for relevant past context.",
			"Use memory_recall when the user references past decisions or asks 'do you remember...'",
		],
		parameters: Type.Object({
			query: Type.String({
				description: "What to search for (natural language or keywords)",
			}),
			scope: Type.Optional(
				StringEnum(["hybrid", "grep", "fts5"] as const, {
					description:
						"Search mode: 'hybrid' (FTS5+grep, default), 'grep' (file), 'fts5' (search index only)",
				}),
			),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const query = params.query as string;
			const scope = (params.scope as string) || "hybrid";

			const args = ["recall", query];
			if (scope === "fts5") args.push("--adapter", "search");
			else if (scope === "grep") args.push("--no-hybrid");
			// hybrid scope = default, no flag needed

			const result = await cliAsync(args, undefined, SEARCH_TIMEOUT);
			const results = (result.results as Array<Record<string, unknown>>) || [];
			const text = formatResults(results, MAX_RECALL_RESULTS);

			lastRecallQuery = query;
			cachedRecall = text;
			lastRecallTime = Date.now();

			updateFooter(ctx, true, results.length);

			return {
				content: [{ type: "text", text }],
				details: { query, scope, count: result.matches || 0 } as Record<
					string,
					unknown
				>,
			};
		},
	});

	// ── LLM Tool: memory_remember ──
	pi.registerTool({
		name: "memory_remember",
		label: "Memory Remember",
		description:
			"Store an important fact, decision, preference, or instruction as a persistent memory. " +
			"Memories survive across sessions and are searchable via memory_recall.",
		promptSnippet:
			"Store a fact, decision, or preference as a persistent memory",
		promptGuidelines: [
			"Use memory_remember when the user states a preference or makes an important decision.",
			"Use memory_remember for architectural decisions, coding conventions, or project patterns.",
			"Remember memories as clear, atomic statements.",
		],
		parameters: Type.Object({
			content: Type.String({
				description: "The memory to store — a clear, self-contained statement",
			}),
			category: Type.Optional(
				StringEnum(["decision", "learning", "preference", "gotcha"] as const, {
					description: "Category hint (optional)",
				}),
			),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const content = params.content as string;
			const category = (params.category as string) || "";

			// Use --direct to bypass trigger/pattern matching
			// --section routes to the correct section header
			const args = ["ingest", "--stdin", "--direct"];
			if (category) args.push("--section", category);
			const result = await cliAsync(args, content);

			const success = (result.status as string) === "ok";
			const text = success
				? `✓ Remembered: ${content}`
				: `✗ Failed to store memory: ${(result.error as string) || "unknown error"}`;

			if (success) updateFooter(ctx, true);

			return {
				content: [{ type: "text", text }],
				details: { content, category, success } as Record<string, unknown>,
			};
		},
	});

	// ── LLM Tool: memory_status ──
	pi.registerTool({
		name: "memory_status",
		label: "Memory Status",
		description: "Show memory system health and entry count.",
		promptSnippet: "Check memory system status and entry count",
		parameters: Type.Object({}),

		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const result = await cliAsync(["status"]);
			const files = (result.files as Record<string, unknown>) || {};
			const health = (result.health as string) || "unknown";
			const bySection = (files.by_section as Record<string, number>) || {};
			const total = (files.total as number) || 0;

			const lines: string[] = [
				`🧠 Agent Memory — ${health === "ok" ? "✅ healthy" : "⚠️ issues"}`,
				`Total entries: ${total}`,
				`Sections: ${Object.keys(bySection).length}`,
			];

			if (Object.keys(bySection).length > 0) {
				lines.push("\nBy section:");
				for (const [section, count] of Object.entries(bySection)) {
					lines.push(`  • ${section}: ${count}`);
				}
			}

			updateFooter(ctx, health === "ok", total);

			return {
				content: [{ type: "text", text: lines.join("\n") }],
				details: {
					health,
					total,
					sections: Object.keys(bySection).length,
				} as Record<string, unknown>,
			};
		},
	});

	// ── Slash Command: /memory-status ──
	pi.registerCommand("memory-status", {
		description: "Show memory system health and stats",
		handler: async (_args, ctx) => {
			const result = await cliAsync(["status"]);
			const health = (result.health as string) || "unknown";
			const files = (result.files as Record<string, unknown>) || {};
			const total = (files.total as number) || 0;
			const issues = (result.issues as Array<unknown>) || [];

			const lines: string[] = [
				`🧠 Agent Memory  —  ${health === "ok" ? "✅ Healthy" : "⚠️ Issues detected"}`,
				`Entries: ${total}  |  Issues: ${issues.length}`,
				`Section count: ${Object.keys((files.by_section as Record<string, number>) || {}).length}`,
				`Config: ${AGENT_MEMORY_DIR}`,
			];

			updateFooter(ctx, health === "ok", total);
			ctx.ui.notify(`Memory: ${total} entries, ${health}`, "info");
			return { message: lines.join("\n") };
		},
	});

	// ── Slash Command: /memory-recall ──
	pi.registerCommand("memory-recall", {
		description: "Search memories. Usage: /memory-recall <query>",
		handler: async (args, ctx) => {
			const query = args?.trim();
			if (!query || query.length < 2) {
				ctx.ui.notify("Usage: /memory-recall <search query>", "warning");
				return;
			}
			const result = await cliAsync(["recall", query]);
			const results = (result.results as Array<Record<string, unknown>>) || [];
			if (results.length > 0) {
				ctx.ui.notify(`Found ${results.length} memory matches`, "info");
			} else {
				ctx.ui.notify("No memory matches found", "info");
			}
			return { message: formatResults(results, 10) };
		},
	});

	// ── Slash Command: /memory-index ──
	pi.registerCommand("memory-index", {
		description: "Rebuild the FTS5 search index",
		handler: async (_args, ctx) => {
			ctx.ui.notify("Rebuilding memory search index...", "info");
			const result = await cliAsync(["index", "--search", "--rebuild"]);
			const search = (result.search as Record<string, unknown>) || {};
			const count = (search.entries_count as number) || 0;
			updateFooter(ctx, true, count);
			ctx.ui.notify(`Index rebuilt: ${count} entries`, "success");
			return { message: `✅ Search index rebuilt: ${count} entries indexed` };
		},
	});

	// ── Slash Command: /memory-inbox ──
	pi.registerCommand("memory-inbox", {
		description: "Show pending compaction inbox items",
		handler: async (_args, ctx) => {
			const result = await cliAsync(["inbox"]);
			const pending = (result.pending_count as number) || 0;
			const processed = (result.processed_count as number) || 0;
			ctx.ui.notify(
				`Inbox: ${pending} pending, ${processed} processed`,
				"info",
			);
			return {
				message: `📥 Inbox: ${pending} pending, ${processed} processed`,
			};
		},
	});

	// ── Auto-recall hook (before_agent_start) ──
	// Disabled during pi --print to avoid feedback loops with consolidation.
	pi.on("before_agent_start", async (_event, ctx) => {
		try {
			// Skip auto-recall in print mode
			if (ctx.mode === "print") return;

			const entries = ctx.sessionManager.getBranch();
			const lastUser = [...entries]
				.reverse()
				.find((e) => e.type === "message" && e.message.role === "user");
			if (!lastUser || lastUser.type !== "message") return;

			const msg = lastUser.message;
			if (msg.role !== "user" || !("content" in msg)) return;

			const queryText =
				typeof msg.content === "string"
					? msg.content
					: Array.isArray(msg.content)
						? msg.content
								.filter(
									(c): c is { type: "text"; text: string } => c.type === "text",
								)
								.map((c) => c.text)
								.join(" ")
						: "";

			if (queryText.length < 10) return;

			// Extract meaningful keywords: strip common question/stop words
			const stopWords = new Set([
				"what",
				"which",
				"where",
				"when",
				"why",
				"how",
				"who",
				"whom",
				"is",
				"are",
				"was",
				"were",
				"be",
				"been",
				"being",
				"do",
				"does",
				"did",
				"done",
				"doing",
				"have",
				"has",
				"had",
				"having",
				"can",
				"could",
				"will",
				"would",
				"shall",
				"should",
				"may",
				"might",
				"the",
				"a",
				"an",
				"this",
				"that",
				"these",
				"those",
				"i",
				"you",
				"he",
				"she",
				"it",
				"we",
				"they",
				"me",
				"him",
				"her",
				"us",
				"them",
				"my",
				"your",
				"his",
				"its",
				"our",
				"their",
				"to",
				"for",
				"of",
				"in",
				"on",
				"at",
				"by",
				"with",
				"about",
				"and",
				"or",
				"but",
				"not",
				"so",
				"if",
				"then",
				"than",
				"from",
				"as",
				"into",
				"through",
				"during",
				"before",
				"after",
				"up",
				"down",
				"out",
				"off",
				"over",
				"under",
				"again",
				"very",
				"just",
				"also",
				"too",
				"only",
				"really",
				"tell",
				"know",
			]);
			const keywords = queryText
				.replace(/[?.,!;:']/g, " ")
				.split(/\s+/)
				.filter((w) => w.length > 2 && !stopWords.has(w.toLowerCase()))
				.join(" ");

			// If no meaningful keywords extracted, skip auto-recall
			if (keywords.length < 3) return;

			// Cache check (use keywords for cache key)
			const now = Date.now();
			if (
				keywords === lastRecallQuery &&
				cachedRecall &&
				now - lastRecallTime < RECALL_CACHE_TTL
			) {
				return {
					message: {
						customType: "memory-context",
						content: cachedRecall,
						display: false,
					},
				};
			}

			// Run recall with extracted keywords (not raw queryText)
			const result = await cliAsync(["recall", keywords]);
			const results = (result.results as Array<Record<string, unknown>>) || [];
			if (results.length === 0) return;

			// Dedup near-identical entries (e.g. same user profile from different sessions)
			const deduped = dedupResults(results);
			if (deduped.length === 0) return;

			const parts: string[] = ["[Recalled from persistent memory]"];
			for (const r of deduped.slice(0, 3)) {
				const content = String(r.content || "").slice(0, 300);
				parts.push(`• ${content}`);
			}
			const recallContent = parts.join("\n");

			lastRecallQuery = keywords;
			cachedRecall = recallContent;
			lastRecallTime = now;

			updateFooter(ctx, true, results.length);

			return {
				message: {
					customType: "memory-context",
					content: recallContent,
					display: false,
				},
			};
		} catch {
			// Silent fallthrough — auto-recall is best-effort
			return;
		}
	});

	// ── Session start: check system health, show footer badge ──
	pi.on("session_start", async (_event, ctx) => {
		try {
			const result = await cliAsync(["status"]);
			const health = (result.health as string) || "unknown";
			const files = (result.files as Record<string, unknown>) || {};
			const total = (files.total as number) || 0;
			updateFooter(ctx, health === "ok", total);
		} catch {
			updateFooter(ctx, false);
		}
	});

	// ── Session shutdown: consolidate learnings on quit ──
	// Fire-and-forget — never blocks the shutdown process.
	pi.on("session_shutdown", async (event, _ctx) => {
		const evt = event as { reason?: string };
		if (evt.reason !== "quit") return; // Only consolidate on explicit quit

		try {
			// Non-blocking: fire and forget
			cliAsync(["consolidate", "--source", "pi"]).catch(() => {});
		} catch {
			// Silent — session is shutting down, best-effort only
		}
	});
}
