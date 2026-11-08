import * as vscode from "vscode";
import { execFlua, fluaExecutable } from "./flua";

/** The hub resource cache (design: docs/notes/notes-vscode-qa-cache.md):
 * downloaded .fqa packages live in the extension's global storage, keyed
 * by hub serial and device id, with a small meta file carrying the hub's
 * `modified` timestamp. Freshness is decided from the hubList data the
 * tree already fetched — the expensive export runs only when the cached
 * copy is missing or stale. */

interface CacheMeta {
  modified: number | null;
  fetchedAt: number;
  name: string;
}

export interface CachedQa {
  id: number;
  name: string;
  modified?: number | null;
}

export class QaCache {
  /** Entries unused for this long are swept on extension activation. */
  static readonly MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

  constructor(private readonly context: vscode.ExtensionContext) {}

  private dir(hubSerial: string): vscode.Uri {
    return vscode.Uri.joinPath(this.context.globalStorageUri, "hc3-cache", hubSerial);
  }

  private fqaUri(hubSerial: string, id: number): vscode.Uri {
    return vscode.Uri.joinPath(this.dir(hubSerial), `${id}.fqa`);
  }

  private metaUri(hubSerial: string, id: number): vscode.Uri {
    return vscode.Uri.joinPath(this.dir(hubSerial), `${id}.json`);
  }

  private async readMeta(uri: vscode.Uri): Promise<CacheMeta | undefined> {
    try {
      const raw = await vscode.workspace.fs.readFile(uri);
      return JSON.parse(Buffer.from(raw).toString("utf8")) as CacheMeta;
    } catch {
      return undefined;
    }
  }

  private async fresh(hubSerial: string, qa: CachedQa): Promise<boolean> {
    try {
      await vscode.workspace.fs.stat(this.fqaUri(hubSerial, qa.id));
    } catch {
      return false;
    }
    const meta = await this.readMeta(this.metaUri(hubSerial, qa.id));
    if (!meta) {
      return false;
    }
    // both sides must know the timestamp to compare; an unknown modified
    // on either side means "assume stale" (one extra export, never wrong)
    return (
      qa.modified !== undefined &&
      qa.modified !== null &&
      meta.modified !== undefined &&
      meta.modified !== null &&
      meta.modified === qa.modified
    );
  }

  /** The cached .fqa for this QA, downloading (one export call) when the
   * cache is missing or the hub's modified timestamp moved on. */
  async ensure(hubSerial: string, qa: CachedQa): Promise<vscode.Uri | undefined> {
    const fqa = this.fqaUri(hubSerial, qa.id);
    if (await this.fresh(hubSerial, qa)) {
      return fqa;
    }
    try {
      await vscode.workspace.fs.createDirectory(this.dir(hubSerial));
    } catch {
      // the directory may exist — createDirectory is not idempotent
    }
    const result = await execFlua(fluaExecutable(), [
      "--tool",
      "downloadFQA",
      String(qa.id),
      "-o",
      fqa.fsPath,
      "-f",
    ]);
    if (result.code !== 0) {
      void vscode.window.showWarningMessage(
        `flua: cannot download QA ${qa.id} — ${result.stderr.trim() || result.stdout.trim()}`
      );
      return undefined;
    }
    const meta: CacheMeta = {
      modified: qa.modified ?? null,
      fetchedAt: Date.now(),
      name: qa.name,
    };
    await vscode.workspace.fs.writeFile(
      this.metaUri(hubSerial, qa.id),
      Buffer.from(JSON.stringify(meta), "utf8")
    );
    return fqa;
  }

  /** Sweep cache entries unused for MAX_AGE_MS (both the .fqa and its
   * meta). Fire-and-forget on activation; never touches workspace files. */
  async prune(): Promise<void> {
    const root = vscode.Uri.joinPath(this.context.globalStorageUri, "hc3-cache");
    let hubs: [string, vscode.FileType][];
    try {
      hubs = await vscode.workspace.fs.readDirectory(root);
    } catch {
      return; // no cache yet
    }
    const cutoff = Date.now() - QaCache.MAX_AGE_MS;
    for (const [name, type] of hubs) {
      if (type !== vscode.FileType.Directory) {
        continue;
      }
      const hubDir = vscode.Uri.joinPath(root, name);
      let entries: [string, vscode.FileType][];
      try {
        entries = await vscode.workspace.fs.readDirectory(hubDir);
      } catch {
        continue;
      }
      for (const [file, ftype] of entries) {
        if (ftype !== vscode.FileType.File || !file.endsWith(".json")) {
          continue;
        }
        const meta = await this.readMeta(vscode.Uri.joinPath(hubDir, file));
        if (!meta || meta.fetchedAt >= cutoff) {
          continue;
        }
        const id = file.slice(0, -".json".length);
        for (const suffix of [".json", ".fqa"]) {
          try {
            await vscode.workspace.fs.delete(vscode.Uri.joinPath(hubDir, `${id}${suffix}`));
          } catch {
            // already gone — fine
          }
        }
      }
    }
  }
}
