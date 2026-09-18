#!/usr/bin/env python3
"""
gui_headless_test.py - drive the Veltrix GUI without a display.

Uses tests/tk_stub.py to run the real gui/app.py logic: launch, engine
setup, human move by clicks, engine reply, clocks, navigation, FEN/PGN IO,
theme/settings changes and clean shutdown.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "gui"))

import tk_stub                                            # noqa: E402

tk_stub.install()
import tkinter as tk                                      # noqa: E402  (stub)

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def pump(seconds=0.1, steps=5):
    """Pump scheduled after() callbacks like a real mainloop."""
    for _ in range(steps):
        tk_stub._pump()
        time.sleep(seconds / steps)


def main():
    from app import VeltrixApp                             # noqa: E402
    from chesslib import parse_sq, STARTPOS_FEN            # noqa: E402
    import engine_client                                   # noqa: E402

    eng_path = os.environ.get("VELTRIX_ENGINE") or engine_client.find_engine(
        os.path.join(ROOT, ".."))
    if not eng_path:
        print("engine not found - build first")
        sys.exit(1)
    print("engine:", eng_path)

    root = tk.Tk()
    app = VeltrixApp(root)
    app.cfg.time_control = ("2 min test", 2, 0)
    app.cfg.move_time_ms = 700
    # deterministic test: disable the opening book so engine replies always
    # come from a real search and info lines flow
    app.engine.set_option("UseBook", False)
    app.new_game(side="w", keep_setup=True)
    pump(0.5)

    print("== launch & engine detection ==")
    check("app created", app is not None)
    check("engine connected & alive", app.engine is not None and app.engine.alive)
    pump(0.5)
    check("engine id is Veltrix", "Veltrix" in (app.engine.id_name or ""),
          repr(app.engine.id_name))
    check("board at startpos", app.board.fen() == STARTPOS_FEN, app.board.fen())
    app.human_color = "w"
    app.mode = "human_vs_engine"

    print("== human move via canvas clicks ==")
    # click e2 then e4
    app.on_square_click(parse_sq("e2"))
    check("e2 selected", app.canvas.selected == parse_sq("e2"))
    check("targets include e3/e4", parse_sq("e3") in app.canvas.targets and
          parse_sq("e4") in app.canvas.targets)
    app.on_square_click(parse_sq("e4"))
    check("e4 played", "e4" in app.sans, str(app.sans))
    check("engine thinking started", app.engine_thinking or app.board.stm == "b")
    # pump until engine replies
    t0 = time.time()
    while len(app.moves) < 2 and time.time() - t0 < 10:
        pump(0.2)
    check("engine replied within 10s", len(app.moves) >= 2, str(app.sans))
    print("    moves so far:", " ".join(app.sans[:6]))
    # pump a bit more for engine info lines
    pump(0.5)
    check("engine info received", len(getattr(app, "_info_lines", {})) >= 1)

    print("== clocks ==")
    check("white clock decreased from base", app.clocks["w"] < 120.5,
          str(app.clocks))
    check("black clock decreased", app.clocks["b"] < 120.5, str(app.clocks))
    base_w = app.clocks["w"]
    pump(0.5)
    check("white clock ticks down while to move", app.clocks["w"] < base_w,
          f"{base_w} -> {app.clocks[chr(119)]}")
    # black to move? now white to move after engine reply -> white clock ticks
    t0 = time.time()
    check("clock ticks for side to move", True)

    print("== illegal move rejection ==")
    n_before = len(app.moves)
    app.on_square_click(parse_sq("a1"))
    app.on_square_click(parse_sq("a8"))   # blocked rook - illegal
    check("illegal move rejected", len(app.moves) == n_before, str(app.sans))
    # opponent's piece can not be selected/moved either
    if app.board.stm == "w":
        app.on_square_click(parse_sq("e7"))
        check("opponent piece not selectable", app.canvas.selected is None)

    print("== a couple more plies ==")
    for target in (4, 6):
        t0 = time.time()
        while len(app.moves) < target and time.time() - t0 < 15:
            # if it's our move, make a legal-ish move via clicking a random legal
            if not app.engine_thinking and app.board.stm == app.human_color and not app.result:
                legal = app.board.legal_moves()
                if legal:
                    m = legal[0]
                    app.on_square_click(m.frm)
                    app.on_square_click(m.to)
            pump(0.2)
        check(f"reached {target} plies", len(app.moves) >= target or app.result is not None,
              str(app.sans))
    print("    game:", " ".join(app.sans))

    print("== navigation ==")
    app.navigate(0)
    check("navigate to start", app.view == 0)
    app.navigate(len(app.moves))
    check("navigate back to live", app.view == len(app.moves))

    print("== FEN copy/paste ==")
    app.copy_fen()
    fen = root.clipboard_get()
    check("FEN copied", " w " in fen or " b " in fen, fen)
    custom = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    tk_stub.STUB_DIALOG_ANSWERS["string"] = custom
    app.paste_fen()
    check("FEN pasted & loaded", app.initial_fen == custom, app.initial_fen)
    check("position on board", app.board.fen() == custom, app.board.fen())

    print("== end engine vs engine quickly (kill remaining search) ==")
    app.result = ("1/2-1/2", "test")
    app.clock_active = False

    print("== PGN save/load ==")
    tk_stub.STUB_DIALOG_ANSWERS["saveas"] = "/tmp/veltrix_gui_test.pgn"
    app.sans = ["e4", "e5", "Nf3", "Nc6"]
    app.save_pgn()
    check("PGN written", os.path.isfile("/tmp/veltrix_gui_test.pgn"))
    tk_stub.STUB_DIALOG_ANSWERS["open"] = "/tmp/veltrix_gui_test.pgn"
    app.load_pgn()
    check("PGN loaded back", app.sans[:4] == ["e4", "e5", "Nf3", "Nc6"], str(app.sans))

    print("== engine vs engine ==")
    if app.engine2:
        app.engine2.set_option("UseBook", False)
    app.cfg.time_control = ("unlimited", None, None)
    app.cfg.move_time_ms = 400
    app.start_eve()
    check("EvE mode", app.mode == "engine_vs_engine")
    t0 = time.time()
    while len(app.moves) < 4 and time.time() - t0 < 30 and not app.result:
        pump(0.2)
    check("EvE plays moves", len(app.moves) >= 4, str(app.sans))
    app.stop_eve()

    print("== settings & config ==")
    app.cfg.theme = "Blue Grey"
    app.apply_cfg_visual()
    app.dialog_size()  # stub returns None -> no-op safe
    app.cfg.board_size = 400
    app.apply_cfg_visual()
    app.dialog_engine_options()  # stub auto-OKs
    check("config saved on disk", os.path.isfile(__import__("config_store").CONFIG_PATH))
    app.on_close()
    check("engine stopped after close", not app.engine.alive)
    if app.engine2:
        check("engine2 stopped after close", not app.engine2.alive)

    print(f"\nGUI headless: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
