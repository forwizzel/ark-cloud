import { useEffect, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import {
  systemRequest,
  type HostPolicy,
  type TerminalGrant,
} from "./systemApi";
import "@xterm/xterm/css/xterm.css";

export default function SystemTerminal({
  csrf,
  policy,
  live,
  hidden,
}: {
  csrf: string;
  policy: HostPolicy | null;
  live: boolean;
  hidden: boolean;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const session = useRef<string | null>(null);
  const connectButton = useRef<HTMLButtonElement>(null);
  const endButton = useRef<HTMLButtonElement>(null);
  const [grant, setGrant] = useState<TerminalGrant | null>(null);
  const [state, setState] = useState("Disconnected");
  const [hasSession, setHasSession] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      socket.current?.close();
      terminal.current?.dispose();
      if (session.current)
        void systemRequest(
          `/admin/system/terminal/sessions/${session.current}/end`,
          csrf,
          {},
        ).catch(() => {});
    };
  }, [csrf]);

  useEffect(() => {
    if (!grant || !surface.current) return;
    let stopped = false;
    let observer: ResizeObserver | undefined;
    let disposeData: { dispose(): void } | undefined;
    let disposeResize: { dispose(): void } | undefined;
    let themeObserver: MutationObserver | undefined;
    const target = surface.current;
    async function attach() {
      const [{ Terminal: Emulator }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (stopped) return;
      const emulator =
        terminal.current ??
        new Emulator({
          fontFamily: '"IBM Plex Mono", monospace',
          fontSize: 13,
          scrollback: 2000,
          cursorBlink: true,
          allowProposedApi: false,
          screenReaderMode: true,
        });
      const fit = new FitAddon();
      if (!terminal.current) {
        terminal.current = emulator;
        emulator.open(target);
        emulator.attachCustomKeyEventHandler((event) => {
          if (
            event.key === "Escape" &&
            event.ctrlKey &&
            event.shiftKey &&
            event.type === "keydown"
          ) {
            endButton.current?.focus();
            return false;
          }
          return true;
        });
      }
      emulator.loadAddon(fit);
      function theme() {
        const styles = getComputedStyle(target);
        emulator.options.theme = {
          background: styles.getPropertyValue("--panel").trim(),
          foreground: styles.getPropertyValue("--ink").trim(),
          cursor: styles.getPropertyValue("--signal").trim(),
          selectionBackground: styles.getPropertyValue("--panel-raised").trim(),
        };
      }
      theme();
      themeObserver = new MutationObserver(theme);
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme", "data-contrast"],
      });
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/system/terminal/${grant!.id}`,
      );
      socket.current = ws;
      const resize = () => {
        if (target.clientWidth === 0) return;
        fit.fit();
        if (ws.readyState === WebSocket.OPEN)
          ws.send(
            JSON.stringify({
              type: "resize",
              cols: emulator.cols,
              rows: emulator.rows,
            }),
          );
      };
      observer = new ResizeObserver(resize);
      observer.observe(target);
      ws.onopen = () => {
        ws.send(JSON.stringify({ grant: grant!.grant }));
        resize();
        setState("Connected");
      };
      ws.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        if (frame.type === "output")
          emulator.write(
            Uint8Array.from(atob(frame.data), (char) => char.charCodeAt(0)),
          );
        else if (frame.type === "notice")
          emulator.writeln(`\r\n${frame.message}\r\n`);
        else if (frame.type === "ended") {
          session.current = null;
          setHasSession(false);
          setState("Ended");
          ws.close();
        }
      };
      ws.onclose = () => {
        if (!stopped && mounted.current)
          setState(session.current ? "Connection interrupted" : "Ended");
      };
      ws.onerror = () =>
        setError(
          "Terminal connection failed. Try reconnecting while the host is online.",
        );
      disposeData = emulator.onData((data) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const encoded = new TextEncoder().encode(data);
        for (let offset = 0; offset < encoded.length; offset += 8192) {
          ws.send(
            JSON.stringify({
              type: "input",
              data: btoa(
                String.fromCharCode(...encoded.slice(offset, offset + 8192)),
              ),
            }),
          );
        }
      });
      disposeResize = { dispose: () => fit.dispose() };
      resize();
    }
    void attach().catch(() =>
      setError(
        "Terminal could not initialize. Refresh the page and try again.",
      ),
    );
    return () => {
      stopped = true;
      observer?.disconnect();
      themeObserver?.disconnect();
      disposeData?.dispose();
      disposeResize?.dispose();
      socket.current?.close();
    };
  }, [grant]);

  async function connect() {
    setError("");
    setState("Connecting…");
    try {
      const result = await systemRequest<TerminalGrant>(
        session.current
          ? `/admin/system/terminal/sessions/${session.current}/attach`
          : "/admin/system/terminal/sessions",
        csrf,
        {},
      );
      if (!mounted.current) {
        void systemRequest(
          `/admin/system/terminal/sessions/${result.id}/end`,
          csrf,
          {},
        );
        return;
      }
      session.current = result.id;
      setHasSession(true);
      setGrant(result);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Terminal is unavailable.",
      );
      setState("Disconnected");
      session.current = null;
      setHasSession(false);
    }
  }
  async function end() {
    try {
      if (session.current)
        await systemRequest(
          `/admin/system/terminal/sessions/${session.current}/end`,
          csrf,
          {},
        );
      session.current = null;
      setHasSession(false);
      socket.current?.close();
      setGrant(null);
      setState("Ended");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not end the session.",
      );
    }
  }

  return (
    <section
      className={`panel host-terminal ${expanded ? "host-terminal--expanded" : ""}`}
      hidden={hidden}
      aria-label="Terminal"
    >
      <header className="host-panel-heading">
        <div>
          <h2>Terminal</h2>
          <p>{policy ? `${policy.account} · ${policy.shell}` : "Host shell"}</p>
        </div>
        <div className="host-actions">
          <span role="status">{state}</span>
          <button
            ref={connectButton}
            onClick={() => void connect()}
            disabled={
              !live ||
              !policy?.terminal ||
              state === "Connected" ||
              state === "Connecting…"
            }
          >
            {hasSession ? "Reconnect" : "Connect"}
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            aria-pressed={expanded}
          >
            {expanded ? "Restore" : "Expand"}
          </button>
          <button
            ref={endButton}
            disabled={!hasSession}
            onClick={() => void end()}
          >
            End session
          </button>
        </div>
      </header>
      {error && (
        <p className="system-warning" role="alert">
          {error}
        </p>
      )}
      {!policy?.terminal && (
        <p>
          Terminal access is disabled.{" "}
          <a href="#administration/system">
            Manage terminal access in Administration → System.
          </a>
        </p>
      )}
      <div
        ref={surface}
        className="host-terminal-surface"
        aria-label="Interactive host terminal"
      />
      <p className="host-caption">
        Runs as the enrolled host account. Select the terminal to type; press
        Ctrl+Shift+Escape to return to page controls. Reconnect within 30
        seconds after an interruption.
      </p>
    </section>
  );
}
