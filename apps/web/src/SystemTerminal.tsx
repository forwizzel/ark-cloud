import { useEffect, useRef, useState } from "react";
import type { Terminal } from "@xterm/xterm";
import {
  systemRequest,
  SystemRequestError,
  type HostPolicy,
  type TerminalGrant,
} from "./systemApi";
import "@xterm/xterm/css/xterm.css";

type TerminalState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "interrupted"
  | "ending"
  | "ended";
const stateLabels: Record<TerminalState, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting…",
  connected: "Connected",
  interrupted: "Connection interrupted",
  ending: "Ending…",
  ended: "Ended",
};

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
  const expandButton = useRef<HTMLButtonElement>(null);
  const overlay = useRef<HTMLDialogElement>(null);
  const operation = useRef(false);
  const reconnectDeadline = useRef<number | null>(null);
  const [grant, setGrant] = useState<TerminalGrant | null>(null);
  const [state, setState] = useState<TerminalState>("disconnected");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [hasSession, setHasSession] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [previousHidden, setPreviousHidden] = useState(hidden);
  const mounted = useRef(true);

  if (previousHidden !== hidden) {
    setPreviousHidden(hidden);
    if (hidden) setExpanded(false);
  }

  useEffect(() => {
    const element = overlay.current;
    if (!element) return;
    if (expanded && !hidden) {
      element.removeAttribute("open");
      element.showModal();
    } else {
      element.close();
      if (!hidden) element.setAttribute("open", "");
    }
  }, [expanded, hidden]);

  useEffect(() => {
    if (state !== "interrupted" || reconnectDeadline.current === null) return;
    const update = () =>
      setRemaining(
        Math.max(
          0,
          Math.ceil((reconnectDeadline.current! - Date.now()) / 1000),
        ),
      );
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [state]);

  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () => {
      overlay.current?.style.setProperty(
        "--terminal-viewport-height",
        `${viewport?.height ?? window.innerHeight}px`,
      );
      overlay.current?.style.setProperty(
        "--terminal-viewport-top",
        `${viewport?.offsetTop ?? 0}px`,
      );
    };
    resize();
    viewport?.addEventListener("resize", resize);
    viewport?.addEventListener("scroll", resize);
    window.addEventListener("resize", resize);
    return () => {
      viewport?.removeEventListener("resize", resize);
      viewport?.removeEventListener("scroll", resize);
      window.removeEventListener("resize", resize);
    };
  }, []);

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
            event.preventDefault();
            (endButton.current?.disabled
              ? expandButton.current
              : endButton.current
            )?.focus();
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
        if (stopped) return;
        ws.send(JSON.stringify({ grant: grant!.grant }));
        resize();
        reconnectDeadline.current = null;
        setRemaining(null);
        setState("connected");
      };
      ws.onmessage = (event) => {
        if (stopped) return;
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
          setState((current) => (current === "ending" ? current : "ended"));
          ws.close();
        }
      };
      ws.onclose = () => {
        if (!stopped && mounted.current) {
          if (session.current && reconnectDeadline.current === null)
            reconnectDeadline.current =
              Date.now() + grant!.reconnect_seconds * 1000;
          setState((current) =>
            current === "ending"
              ? current
              : session.current
                ? "interrupted"
                : "ended",
          );
        }
      };
      ws.onerror = () => {
        if (stopped) return;
        setError(
          "Terminal connection failed. Try reconnecting while the host is online.",
        );
        ws.close();
      };
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
    void attach().catch(() => {
      if (stopped || !mounted.current) return;
      stopped = true;
      observer?.disconnect();
      themeObserver?.disconnect();
      disposeData?.dispose();
      disposeResize?.dispose();
      socket.current?.close();
      terminal.current?.dispose();
      terminal.current = null;
      if (reconnectDeadline.current === null)
        reconnectDeadline.current = Date.now() + grant.reconnect_seconds * 1000;
      setState("interrupted");
      setError(
        "Terminal could not initialize. Try reconnecting or end this session.",
      );
    });
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
    if (operation.current) return;
    operation.current = true;
    setError("");
    setState("connecting");
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
        ).catch(() => {});
        return;
      }
      session.current = result.id;
      setHasSession(true);
      setGrant(result);
    } catch (cause) {
      if (!mounted.current) return;
      setError(
        cause instanceof Error ? cause.message : "Terminal is unavailable.",
      );
      if (
        cause instanceof SystemRequestError &&
        [404, 410].includes(cause.status)
      ) {
        session.current = null;
        setHasSession(false);
        setGrant(null);
        reconnectDeadline.current = null;
        setRemaining(null);
        setState("ended");
      } else setState(session.current ? "interrupted" : "disconnected");
    } finally {
      operation.current = false;
    }
  }
  async function end() {
    if (operation.current || !session.current) return;
    operation.current = true;
    const previous = state;
    setState("ending");
    setError("");
    try {
      if (session.current)
        await systemRequest(
          `/admin/system/terminal/sessions/${session.current}/end`,
          csrf,
          {},
        );
      if (!mounted.current) return;
      session.current = null;
      setHasSession(false);
      socket.current?.close();
      setGrant(null);
      reconnectDeadline.current = null;
      setRemaining(null);
      setState("ended");
    } catch (cause) {
      if (!mounted.current) return;
      setError(
        cause instanceof Error ? cause.message : "Could not end the session.",
      );
      setState(
        socket.current?.readyState === WebSocket.OPEN
          ? "connected"
          : previous === "connected"
            ? "interrupted"
            : previous,
      );
    } finally {
      operation.current = false;
    }
  }

  return (
    <dialog
      ref={overlay}
      className={`panel host-terminal ${expanded ? "host-terminal--expanded" : ""}`}
      aria-label={expanded ? "Expanded terminal" : "Terminal"}
      aria-modal={expanded ? true : undefined}
      aria-describedby="host-terminal-help"
      onCancel={(event) => {
        event.preventDefault();
        if (!surface.current?.contains(document.activeElement)) {
          setExpanded(false);
          expandButton.current?.focus();
        }
      }}
    >
      <header className="host-panel-heading">
        <div>
          <h2>Terminal</h2>
          <p>{policy ? `${policy.account} · ${policy.shell}` : "Host shell"}</p>
        </div>
        <div className="host-actions">
          <span role="status">{stateLabels[state]}</span>
          <button
            ref={connectButton}
            onClick={() => void connect()}
            disabled={
              !live ||
              !policy?.terminal ||
              state === "connected" ||
              state === "connecting" ||
              state === "ending" ||
              (hasSession && remaining === 0)
            }
          >
            {hasSession ? "Reconnect" : "Connect"}
          </button>
          <button
            ref={expandButton}
            onClick={() => {
              setExpanded(!expanded);
              expandButton.current?.focus();
            }}
            aria-pressed={expanded}
          >
            {expanded ? "Restore" : "Expand"}
          </button>
          <button
            ref={endButton}
            disabled={
              !hasSession || state === "ending" || state === "connecting"
            }
            onClick={() => void end()}
          >
            {state === "ending" ? "Ending session…" : "End session"}
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
      <button
        onClick={() => {
          terminal.current?.blur();
          (endButton.current?.disabled
            ? expandButton.current
            : endButton.current
          )?.focus();
        }}
      >
        Exit terminal input
      </button>
      <p className="host-caption" id="host-terminal-help">
        Runs as the enrolled host account. Select the terminal to type; press
        Ctrl+Shift+Escape to return to page controls. Escape is sent to the
        shell while typing.
        {state === "interrupted" &&
          remaining !== null &&
          (remaining > 0
            ? ` Reconnect within ${remaining} seconds.`
            : " Reconnect window expired. End this session before starting another.")}
      </p>
    </dialog>
  );
}
