/**
 * Memento — compaction capture extension
 *
 * Hooks session_before_compact to capture messages about to be lost during compaction
 * and writes them to ~/.agent-memory/inbox/compaction/ for later consolidation.
 *
 * Also hooks session_compact to record the resulting compaction entry for observability.
 *
 * Design: Zero-risk. Exits silently on any error. Never blocks compaction.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { join } from "node:path";
import { writeFile, mkdir, symlink, unlink } from "node:fs/promises";
import { existsSync } from "node:fs";

// ── Configuration ────────────────────────────────────────────────

const INBOX_DIR = join(
	process.env.AGENT_MEMORY_DIR ||
		join(process.env.HOME || "/tmp", ".agent-memory"),
	"inbox",
	"compaction",
);

const MAX_WRITE_RETRIES = 3;

// ── Helper: safe write with retries ──────────────────────────────

async function safeWrite(filePath: string, data: string): Promise<boolean> {
	for (let attempt = 0; attempt < MAX_WRITE_RETRIES; attempt++) {
		try {
			await mkdir(INBOX_DIR, { recursive: true });
			await writeFile(filePath, data, { encoding: "utf-8", flag: "wx" });
			return true;
		} catch (err: unknown) {
			// File already exists — append a counter suffix
			if ((err as NodeJS.ErrnoException).code === "EEXIST") {
				const dot = filePath.lastIndexOf(".");
				const base = dot > 0 ? filePath.slice(0, dot) : filePath;
				const ext = dot > 0 ? filePath.slice(dot) : "";
				filePath = `${base}.${attempt + 1}${ext}`;
				continue;
			}
			// ENOENT on the INBOX_DIR (rare race with cleanup)
			if ((err as NodeJS.ErrnoException).code === "ENOENT") {
				try {
					await mkdir(INBOX_DIR, { recursive: true });
					await writeFile(filePath, data, { encoding: "utf-8" });
					return true;
				} catch {
					return false;
				}
			}
			return false;
		}
	}
	return false;
}

// ── Helper: session-safe filename ────────────────────────────────

function safeId(raw: string): string {
	return raw.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64);
}

// ── Helper: serialize a single message to compact JSONL line ─────

interface CompactMessage {
	role: string;
	content: string;
	toolCalls?: Array<{ name: string; args: Record<string, unknown> }>;
	timestamp: number;
}

function serializeMessage(msg: Record<string, unknown>): CompactMessage {
	const role = String(msg.role || "unknown");
	const timestamp =
		typeof msg.timestamp === "number" ? msg.timestamp : Date.now();

	// Extract text content
	let content = "";
	const rawContent = msg.content;
	if (typeof rawContent === "string") {
		content = rawContent;
	} else if (Array.isArray(rawContent)) {
		content = rawContent
			.filter(
				(c: unknown): c is { type?: string; text?: string } =>
					typeof c === "object" &&
					c !== null &&
					(c as Record<string, unknown>).type === "text",
			)
			.map((c) => c.text || "")
			.join("\n");
	}

	// Extract tool calls (function_call style)
	const toolCalls: Array<{ name: string; args: Record<string, unknown> }> = [];
	const rawToolCalls =
		msg.toolCalls || (msg as Record<string, unknown>).function_call;
	if (Array.isArray(rawToolCalls)) {
		for (const tc of rawToolCalls) {
			if (typeof tc === "object" && tc !== null) {
				const rtc = tc as Record<string, unknown>;
				toolCalls.push({
					name: String(rtc.name || rtc.function?.name || rtc.id || ""),
					args: (typeof rtc.arguments === "object" && rtc.arguments !== null
						? rtc.arguments
						: typeof rtc.arguments === "string"
							? tryParseJson(rtc.arguments as string)
							: {}) as Record<string, unknown>,
				});
			}
		}
	} else if (rawToolCalls && typeof rawToolCalls === "object") {
		const ftc = rawToolCalls as Record<string, unknown>;
		toolCalls.push({
			name: String(ftc.name || ""),
			args: (typeof ftc.arguments === "object" && ftc.arguments !== null
				? ftc.arguments
				: {}) as Record<string, unknown>,
		});
	}

	return { role, content, toolCalls, timestamp };
}

function tryParseJson(s: string): Record<string, unknown> | string {
	try {
		return JSON.parse(s);
	} catch {
		return s;
	}
}

// ── Helper: infer session ID from session file path ──────────────

function inferSessionId(ctx: {
	sessionManager?: { getSessionFile?: () => string | undefined };
}): string {
	try {
		const sf = ctx.sessionManager?.getSessionFile?.();
		if (sf) {
			const base = sf.split("/").pop() || sf;
			return safeId(base.replace(/\.jsonl$/i, ""));
		}
	} catch {
		// sessionManager may not be available
	}
	return `unknown-${Date.now()}`;
}

// ── Extension Entry Point ────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	// ── Event: session_before_compact ──────────────────────────────
	// Captures messages about to be consolidated/summarized away.

	pi.on("session_before_compact", async (event, ctx) => {
		// Destructure with defaults to be resilient against API changes
		const {
			preparation = {} as Record<string, unknown>,
			reason = "unknown",
			willRetry = false,
		} = event as Record<string, unknown>;

		const {
			messagesToSummarize = [],
			turnPrefixMessages = [],
			tokensBefore = 0,
			firstKeptEntryId = "",
			previousSummary = "",
			settings = {},
		} = preparation as Record<string, unknown>;

		// Only capture if there are actual messages
		const allMessages = [
			...(Array.isArray(messagesToSummarize) ? messagesToSummarize : []),
			...(Array.isArray(turnPrefixMessages) ? turnPrefixMessages : []),
		];

		if (allMessages.length === 0) {
			return; // nothing to capture
		}

		// Build metadata
		const ts = Date.now();
		const tsISO = new Date(ts).toISOString();
		const sessionId = inferSessionId(ctx);

		// ── Write messages.jsonl ────────────────────────────────────
		// One compact JSON object per line.
		const messageLines: string[] = [];
		const seenCustomTypes = new Set<string>();

		for (const msg of allMessages) {
			const raw = msg as Record<string, unknown>;
			const compact = serializeMessage(raw);

			// Skip pure tool-result messages with empty content
			if (
				!compact.content &&
				(!compact.toolCalls || compact.toolCalls.length === 0)
			) {
				continue;
			}

			// Skip custom-type messages we've already seen (dedup on the same compaction)
			if (raw.customType && typeof raw.customType === "string") {
				const dedupKey = `${raw.customType}:${compact.content.slice(0, 100)}`;
				if (seenCustomTypes.has(dedupKey)) continue;
				seenCustomTypes.add(dedupKey);
			}

			messageLines.push(JSON.stringify(compact));
		}

		if (messageLines.length === 0) {
			return; // nothing worth saving
		}

		// Prefix for deterministic filenames
		const prefix = `${ts}-${sessionId}`;

		// Write JSONL
		const jsonlPath = join(INBOX_DIR, `${prefix}.jsonl`);
		const jsonlOk = await safeWrite(jsonlPath, messageLines.join("\n") + "\n");

		// Write metadata
		const metadataPath = join(INBOX_DIR, `${prefix}.metadata.json`);
		const metadata = {
			captured_at: tsISO,
			session_id: sessionId,
			reason,
			will_retry: willRetry,
			messages_captured: messageLines.length,
			tokens_before: tokensBefore,
			first_kept_entry_id: firstKeptEntryId,
			has_previous_summary: !!previousSummary,
			compaction_settings: settings,
			inbox_path: jsonlPath,
		};

		await safeWrite(metadataPath, JSON.stringify(metadata, null, 2));

		// Attempt a "latest" symlink for easy CLI access
		try {
			const latestLink = join(INBOX_DIR, "latest.jsonl");
			if (existsSync(latestLink)) {
				await unlink(latestLink).catch(() => {});
			}
			try {
				await symlink(jsonlPath, latestLink);
			} catch {
				// Fallback: write a latest metadata pointer
				const latestMeta = join(INBOX_DIR, "latest.json");
				await writeFile(
					latestMeta,
					JSON.stringify({ path: jsonlPath, ts: tsISO }, null, 2),
				).catch(() => {});
			}
		} catch {
			// Symlinks may fail on some systems — non-fatal
		}

		// Silent success — never notify or log to avoid cluttering TUI
	});

	// ── Event: session_compact ────────────────────────────────────
	// Logs the completed compaction for observability.

	pi.on("session_compact", async (event, ctx) => {
		const {
			compactionEntry = null,
			reason = "unknown",
			willRetry = false,
		} = event as Record<string, unknown>;

		if (!compactionEntry) return;

		const entry = compactionEntry as Record<string, unknown>;
		const ts = Date.now();
		const sessionId = inferSessionId(ctx);
		const prefix = `${ts}-${sessionId}`;

		// Write a brief .compact.json confirming what happened, linked to the messages file
		const compactLog = join(INBOX_DIR, `${prefix}.compact.json`);
		const logData = {
			completed_at: new Date(ts).toISOString(),
			session_id: sessionId,
			reason,
			will_retry: willRetry,
			entry_id: entry.id || "",
			summary_preview: String(entry.summary || "").slice(0, 200),
			tokens_before: entry.tokensBefore || 0,
		};

		await safeWrite(compactLog, JSON.stringify(logData, null, 2));
	});
}
