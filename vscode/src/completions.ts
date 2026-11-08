import * as vscode from "vscode";
import { execFlua, fluaExecutable } from "./flua";

/** `flua --tool house`'s JSON document — the contract the provider reads. */
interface HouseDevice {
  id: number;
  name: string;
  type: string;
  room: string | null;
}

interface HouseDoc {
  devices: HouseDevice[];
  globals: string[];
  scenes: { id: number; name: string }[];
  customEvents: string[];
}

const TRIGGERS = [
  "\"",
  "'",
  ".",
  " ",
  ...Array.from({ length: 10 }, (_, i) => String(i)),
  ...Array.from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"),
];
const REFRESH_MIN_INTERVAL_MS = 30_000;

let house: HouseDoc | undefined;
let lastFetch = 0;

/** The db/seed file for the simulated house (flua.houseDb) — used when no
 * HC3 credentials exist; the tool resolves the priority itself. */
function houseDb(): string | undefined {
  const db = vscode.workspace.getConfiguration("flua").get<string>("houseDb", "");
  return db || undefined;
}

export async function refreshHouse(): Promise<HouseDoc | undefined> {
  const now = Date.now();
  if (house && now - lastFetch < REFRESH_MIN_INTERVAL_MS) {
    return house;
  }
  const args = ["--tool", "house"];
  const db = houseDb();
  if (db) {
    args.push("--db", db);
  }
  const result = await execFlua(fluaExecutable(), args);
  if (result.code !== 0) {
    house = undefined;
    return undefined;
  }
  try {
    house = JSON.parse(result.stdout) as HouseDoc;
    lastFetch = now;
  } catch {
    house = undefined;
  }
  return house;
}

/** The device-completion contexts: the first argument of these calls is a
 * device id. The already-typed word — id digits or a name fragment — is
 * part of the match and the replace range, so the menu appears at
 * `fibaro.call(` and narrows as you type `fibaro.call(4` or
 * `fibaro.call(Kitchen`; accepting inserts the bare id. */
const DEVICE_CONTEXTS = [
  /fibaro\.call\(\s*[\w ]*$/,
  /fibaro\.getValue\(\s*[\w ]*$/,
  /fibaro\.setValue\(\s*[\w ]*$/,
];
const SCENE_CONTEXT = /fibaro\.scene\(\s*["']execute["']\s*,\s*[\w ]*$/;
const GLOBAL_GET = /fibaro\.getGlobalVariable\(\s*["']([^"']*)$/;
const GLOBAL_SET = /fibaro\.setGlobalVariable\(\s*["']([^"']*)$/;
const CUSTOM_EVENT = /fibaro\.emitCustomEvent\(\s*["']([^"']*)$/;

/** The text range a device/scene id completion replaces: the typed word
 * before the cursor — id digits or a name fragment — or the cursor
 * position itself when nothing is typed yet. */
function wordRange(document: vscode.TextDocument, position: vscode.Position): vscode.Range {
  const line = document.lineAt(position.line);
  let start = position.character;
  while (start > 0 && /[\w ]/.test(line.text[start - 1])) {
    start--;
  }
  return new vscode.Range(position.line, start, position.line, position.character);
}

/** The text range a string completion replaces: after the opening quote,
 * including the already-typed prefix (which doubles as the filter). */
function stringRange(document: vscode.TextDocument, position: vscode.Position): vscode.Range {
  const line = document.lineAt(position.line);
  let start = position.character;
  while (start > 0 && line.text[start - 1] !== "\"" && line.text[start - 1] !== "'") {
    start--;
  }
  return new vscode.Range(position.line, start, position.line, position.character);
}

function deviceItems(
  document: vscode.TextDocument,
  position: vscode.Position
): vscode.CompletionItem[] {
  const items = (house?.devices ?? []).map((dev) => {
    const item = new vscode.CompletionItem(
      `${dev.id} — ${dev.name}`,
      vscode.CompletionItemKind.Value
    );
    item.insertText = String(dev.id);
    item.filterText = `${dev.id} ${dev.name} ${dev.room ?? ""}`;
    item.detail = dev.room ? `${dev.type} · ${dev.room}` : dev.type;
    item.range = wordRange(document, position);
    return item;
  });
  return items;
}

function nameItems(
  names: string[],
  kind: vscode.CompletionItemKind,
  document: vscode.TextDocument,
  position: vscode.Position,
  prefix: string
): vscode.CompletionItem[] {
  const filtered = names.filter((name) => name.startsWith(prefix));
  return filtered.map((name) => {
    const item = new vscode.CompletionItem(name, kind);
    item.insertText = name.slice(prefix.length);
    item.range = stringRange(document, position);
    return item;
  });
}

function completionItems(
  document: vscode.TextDocument,
  position: vscode.Position
): vscode.CompletionItem[] | undefined {
  if (!house) {
    return undefined;
  }
  const lineText = document.lineAt(position.line).text.slice(0, position.character);
  if (DEVICE_CONTEXTS.some((re) => re.test(lineText))) {
    return deviceItems(document, position);
  }
  if (SCENE_CONTEXT.test(lineText)) {
    const items = (house.scenes ?? []).map((scene) => {
      const item = new vscode.CompletionItem(
        `${scene.id} — ${scene.name}`,
        vscode.CompletionItemKind.Value
      );
      item.insertText = String(scene.id);
      item.filterText = `${scene.id} ${scene.name}`;
      item.range = wordRange(document, position);
      return item;
    });
    return items;
  }
  const eventMatch = CUSTOM_EVENT.exec(lineText);
  if (eventMatch) {
    return nameItems(
      house.customEvents ?? [],
      vscode.CompletionItemKind.Event,
      document,
      position,
      eventMatch[1]
    );
  }
  const globalMatch = GLOBAL_GET.exec(lineText) ?? GLOBAL_SET.exec(lineText);
  if (globalMatch) {
    return nameItems(
      house.globals ?? [],
      vscode.CompletionItemKind.Variable,
      document,
      position,
      globalMatch[1]
    );
  }
  return undefined;
}

/** The HT table: rooms → device names → ids, written as a LuaLS-annotated
 * module the QA can require. Room keys that are valid Lua identifiers get
 * field syntax (HT.Kitchen); everything is also reachable by bracket
 * (HT["Living room"]) so no name is ever out of reach. */
function homeTableLua(doc: HouseDoc): string {
  const lines: string[] = [
    "-- ht.lua — the home table: rooms → device names → ids, generated by",
    "-- the flua extension (Flua: Generate home table). Regenerate after",
    "-- the house changes; require() it, or copy the table into your QA:",
    "--   local HT = require(\"ht\")",
    "---@class HT",
    "---@field rooms table",
  ];
  const byRoom = new Map<string, { id: number; name: string }[]>();
  for (const dev of doc.devices) {
    const room = dev.room || "No room";
    const list = byRoom.get(room) ?? [];
    list.push({ id: dev.id, name: dev.name });
    byRoom.set(room, list);
  }
  const validId = /^[A-Za-z_][A-Za-z0-9_]*$/;
  const entries: string[] = [];
  for (const [room, devices] of [...byRoom.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    if (validId.test(room)) {
      lines.push(`---@field ${room} table<string, integer>`);
    }
    // non-identifier room names stay reachable as HT["Room name"]
    for (const dev of devices.sort((a, b) => a.name.localeCompare(b.name))) {
      entries.push(`  ["${room}"] = { ["${dev.name}"] = ${dev.id} },`);
    }
  }
  if (!entries.length) {
    lines.push("--- (no devices in the house)");
  }
  lines.push("HT = {");
  lines.push(...entries);
  lines.push("}");
  return lines.join("\n") + "\n";
}

async function generateHomeTable(): Promise<void> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    void vscode.window.showWarningMessage("flua: open a workspace folder first");
    return;
  }
  const doc = await refreshHouse();
  if (!doc) {
    void vscode.window.showWarningMessage(
      "flua: no house data — set HC3 credentials in .env or flua.houseDb, then refresh"
    );
    return;
  }
  const target = vscode.Uri.joinPath(root, "ht.lua");
  await vscode.workspace.fs.writeFile(target, Buffer.from(homeTableLua(doc), "utf8"));
  void vscode.window.showInformationMessage("flua: wrote ht.lua (the home table)");
}

export function registerCompletions(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      "lua",
      {
        provideCompletionItems: async (document, position) => {
          const doc = house ?? (await refreshHouse());
          if (!doc) {
            return undefined;
          }
          return completionItems(document, position);
        },
      },
      ...TRIGGERS
    ),

    vscode.commands.registerCommand("flua.house.refresh", async () => {
      const doc = await refreshHouse();
      if (doc) {
        void vscode.window.showInformationMessage(
          `flua: house data refreshed (${doc.devices.length} devices)`
        );
      } else {
        void vscode.window.showWarningMessage(
          "flua: cannot read the house — no HC3 credentials or flua.houseDb"
        );
      }
    }),

    vscode.commands.registerCommand("flua.house.generateHomeTable", () =>
      void generateHomeTable()
    )
  );

  const refresh = vscode.workspace.getConfiguration("flua").get<string>("houseRefresh", "onSave");
  if (refresh === "onSave") {
    context.subscriptions.push(
      vscode.workspace.onDidSaveTextDocument((doc) => {
        if (doc.languageId !== "lua") {
          return;
        }
        void refreshHouse(); // throttled internally
      })
    );
  }
}
