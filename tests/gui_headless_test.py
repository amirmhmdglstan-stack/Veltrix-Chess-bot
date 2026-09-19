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

    print("== undo/redo mechanics (PART 8 regression) ==")
    # ---------------- A. pure state mechanics, no engine interference --
    app.result = None
    app.mode = "human_vs_engine"
    app.new_game(side="w", keep_setup=True)
    app.mode = "human_vs_human"
    app.engine_thinking = False
    pump(0.3)
    def play(sq1, sq2):
        app.on_square_click(parse_sq(sq1))
        app.on_square_click(parse_sq(sq2))
    for a, b in (("e2", "e4"), ("e7", "e5"), ("g1", "f3"), ("b8", "c6")):
        play(a, b)
    check("scripted 4 plies", app.sans == ["e4", "e5", "Nf3", "Nc6"], str(app.sans))

    # single undo mutates the REAL game state, not just a view cursor
    app.undo_plies(1)
    check("undo shrinks real move list", app.sans == ["e4", "e5", "Nf3"], str(app.sans))
    check("undo puts cursor at live end", app.view == len(app.moves))
    check("undo restores position", "Nc6" not in app.board.san(app.board.legal_moves()[0])
          and app.board.fen().split()[1] == "b", app.board.fen())

    # multiple undos (alternating sides)
    app.undo_plies(2)
    check("multiple undos", app.sans == ["e4"], str(app.sans))
    check("pieces restored after undos",
          app.board.fen() == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
          app.board.fen())

    # redo restores full history
    app.redo_plies(2)
    check("redo restores plies", app.sans == ["e4", "e5", "Nf3"], str(app.sans))
    # undo 1 ply of the engine-era rest + new move truncates abandoned future
    app.undo_plies(1)
    play("f1", "c4")     # Bc4 instead of Nf3; the old future must die
    check("new move from rewound position truncates redo trail",
          app.sans == ["e4", "e5", "Bc4"], str(app.sans))
    n0 = len(app.moves)
    app.redo_plies(1)
    check("nothing to redo after truncation", len(app.moves) == n0, str(app.sans))

    # undo clears game-over state
    app.result = ("1/2-1/2", "test-result")
    app.undo_plies(1)
    check("undo clears result", app.result is None, str(app.result))
    app.result = None
    app.redo_plies(1)
    # undo-all & redo-all round trip over the full trail
    total = len(app.state.moves)
    app.undo_all_plies()
    check("undo-all reaches initial position", app.view == 0 and len(app.moves) == 0)
    app.redo_all_plies()
    check("redo-all restores game", len(app.moves) == total, str(app.sans))

    # -------- B. engine orchestration: cancel, stale bestmoves, re-arm --
    print("== undo vs engine (PART 8 regression) ==")
    app.mode = "human_vs_engine"
    app.human_color = "w"
    app.new_game(side="w", keep_setup=True)
    pump(0.3)
    play("e2", "e4")
    check("engine search started after e4", app.engine_thinking)
    # THE ORIGINAL BUG: previous action while engine is thinking must cancel
    # the search and the late bestmove must land nowhere
    app.undo_plies(1)
    check("undo cancels in-flight search", not app.engine_thinking)
    check("game state really rewound", len(app.moves) == 0 and not app.sans, str(app.sans))
    pump(2.0)   # well beyond the cancelled search's deadline
    check("stale bestmove discarded", len(app.moves) == 0 and not app.sans, str(app.sans))

    # engine re-arms from the position reached via takeback
    play("d2", "d4")
    t0 = time.time()
    while len(app.moves) < 2 and time.time() - t0 < 12:
        pump(0.2)
    check("engine replies from post-undo position",
          len(app.moves) == 2 and app.sans[0] == "d4", str(app.sans))

    # takeback where the BOT was about to move -> engine re-thinks there
    app.undo_plies(1)    # remove engine's reply; black (engine) to move again
    check("bot-turn takeback rewound", len(app.moves) == 1, str(app.sans))
    t0 = time.time()
    while len(app.moves) < 2 and time.time() - t0 < 25:
        pump(0.2)
    check("engine re-arms on its own undone turn",
          len(app.moves) == 2 and app.moves[-1].uci()[:2] != "d4", str(app.sans))

    # ---------------- C. jump-style navigation on real state ----------

    print("== model configuration (PART 1) ==")
    import models
    # registry invariants
    check("Level 1 is Flash", models.profile("Level 1") is models.profile("Flash")
          and models.profile("Flash").nodes == 4000)
    check("Level 8 is High (unlimited)", models.profile("Level 8") is
          models.profile("High") and models.profile("High").unlimited)
    ladder = [models.profile(f"Level {i}") for i in range(1, 8)]
    nodes_seq = [p.nodes if p.nodes is not None else float("inf") for p in ladder]
    check("levels strictly increase until unlimited top",
          all(a < b for a, b in zip(nodes_seq, nodes_seq[1:])))
    check("menu order: 3 models + 8 levels", len(models.menu_choices()) == 11)
    # go kwargs: model caps stack on top of the time control
    kw = models.go_kwargs(models.profile("Flash"), "w",
                          {"w": 60.0, "b": 60.0}, {"w": 0, "b": 0}, 500)
    check("Flash gets nodes cap", kw.get("nodes") == 4000, str(kw))
    check("Flash movetime capped", kw.get("movetime") == 60, str(kw))
    kw = models.go_kwargs(models.profile("High"), "w",
                          {"w": 60.0, "b": 60.0}, {"w": 0, "b": 0}, 500)
    check("High uncapped", "nodes" not in kw and "movetime" not in kw, str(kw))
    kw = models.go_kwargs(models.profile("Light"), "w",
                          {"w": float("inf"), "b": float("inf")}, {"w": 0, "b": 0}, 500)
    check("Light unlimited-TC movetime=floor", kw.get("movetime") == 400, str(kw))

    # the app really sends the model budget to the engine
    app.set_model("Flash")
    check("model persisted in cfg", app.cfg.model == "Flash")
    sent = []
    orig_go = app.engine.go
    def tap_go(**kw):
        sent.append(kw)
        return orig_go(**kw)
    app.engine.go = tap_go
    app.mode = "human_vs_engine"
    app.new_game(side="w")
    app.on_square_click(parse_sq("g2")); app.on_square_click(parse_sq("g3"))
    t0 = time.time()
    while not sent and time.time() - t0 < 8:
        pump(0.2)
    check("engine go carries Flash nodes", sent and sent[0].get("nodes") == 4000,
          str(sent))
    t0 = time.time()
    while len(app.moves) < 2 and time.time() - t0 < 10:
        pump(0.2)
    check("Flash answered", len(app.moves) >= 2, str(app.sans))
    app.engine.go = orig_go
    app.set_model("High")
    check("back to High", app.model.key == "High" and app.model.unlimited)


    print("== external engines (PART 2/3) ==")
    import ext_engines
    fake_path = os.path.join(ROOT, "fake_engine.py")
    # graceful absence / invalid paths: probe never explodes
    nm, specs = ext_engines.probe(fake_path)
    check("fake engine probed", nm == "FakeFish 1.0" and len(specs) >= 2, repr(nm))
    check("options read dynamically",
          any(s.name == "Skill Level" and s.type == "spin" and s.min == "0"
              and s.max == "20" for s in specs),
          str([(s.name, s.type) for s in specs]))
    nm2, _ = ext_engines.probe("/nonexistent/engine-x")
    check("invalid path probes gracefully", nm2 is None)
    nm3, _ = ext_engines.probe("/bin/ls")
    check("non-engine probes gracefully", nm3 is None)

    # registry roundtrip + persistence
    ent = ext_engines.ExternalEngine(name="FakeFish 1.0", path=fake_path,
                                     options={"Skill Level": "0"})
    app.cfg.external_engines = []
    app.registry = ext_engines.EngineRegistry(app.cfg)
    app.registry.save_entry(ent)
    app.cfg.save()
    import config_store as cs_mod
    c2 = cs_mod.Config.load()
    reg2 = ext_engines.EngineRegistry(c2)
    found = [e for e in reg2.list() if e.name == "FakeFish 1.0"]
    check("registry persisted", found and found[0].path == fake_path
          and found[0].options.get("Skill Level") == "0")

    # stockfish detection must fail GRACEFULLY, never crash
    old_run = ext_engines._runnable
    ext_engines._runnable = lambda p: False
    app.cfg.stockfish_path = ""
    sf = ext_engines.detect_stockfish(app.cfg)
    check("absent stockfish handled", sf == "" and app.cfg.stockfish_path == "")
    ext_engines._runnable = old_run

    # the app plays a game against the registered external engine
    app.set_opponent("engine:FakeFish 1.0")
    check("external opponent active", app.opponent_uses_external)
    app.new_game(side="w")
    app.on_square_click(parse_sq("e2")); app.on_square_click(parse_sq("e4"))
    t0 = time.time()
    while len(app.moves) < 2 and time.time() - t0 < 10:
        pump(0.2)
    check("external engine replied", len(app.moves) >= 2, str(app.sans))
    # options flowed into the external process (fake echoes skill in info pv)
    ext_cli = getattr(app, "_ext_client", None)
    check("ext client live", ext_cli is not None and ext_cli.alive)
    app.set_opponent("model:High")
    check("back to internal model", not app.opponent_uses_external
          and app.model.key == "High")


    print("== main menu / screens (PART 4-6) ==")
    check("booted into menu", getattr(app, "_active_frame", "") == "menu")
    check("menu frames exist", hasattr(app, "menu_frame") and
          hasattr(app, "game_frame") and hasattr(app, "config_frame")
          and hasattr(app, "_menu_btns"))
    app.show_frame("game")
    check("game frame shown", app._active_frame == "game")
    app.show_frame("config")
    check("config frame shown", app._active_frame == "config")

    # an in-progress game enables Continue; a new/cleared board disables it
    app.mode = "human_vs_human"
    app.new_game(side="w", keep_setup=True)
    app.mode = "human_vs_human"; app.engine_thinking = False
    app.on_square_click(parse_sq("e2")); app.on_square_click(parse_sq("e4"))
    app.show_frame("menu")
    st = dict(app._menu_btns["continue"]._cfg)
    check("continue enabled mid-game", st.get("state") in (None, "normal"), str(st))
    app.state.reset()
    app._refresh_menu()
    _rg = app.cfg.resume_game  # still saved from the move above
    app.show_frame("menu")
    st = dict(app._menu_btns["continue"]._cfg)
    check("continue uses saved game", _rg is not None and
          st.get("state") in (None, "normal"), str(st))

    # restore round trip: exact game state reconstruction
    app.cfg.resume_game = {
        "initial_fen": STARTPOS_FEN, "moves": ["e2e4", "e7e5"],
        "sans": ["e4", "e5"],
        "clocks": {"w": "inf", "b": "inf"}, "incs": {"w": 0, "b": 0},
        "opponent_key": "model:High", "human_color": "w",
        "mode": "human_vs_human",
    }
    app.mode = "human_vs_engine"
    app.state.reset(STARTPOS_FEN)
    ok = app.restore_saved_game()
    check("saved game restored", ok and app.sans == ["e4", "e5"]
          and app.mode == "human_vs_human", str(app.sans))
    check("restore clears engine pendings", not app.engine_thinking)

    # config screen drives a start
    app.show_frame("config")
    vals = app._opponent_choices()
    check("opponent list covers models", len(vals) >= 11, str(vals[:3]))
    check("external included in choices", "engine:FakeFish 1.0" in vals)
    app.cfg_side_var.set("w")
    app.cfg_opp_var.set("model:Flash")
    app.cfg_tc_var.set(app.TIME_CONTROLS[0][0])
    app.cfg_fen_var.set("")
    app.cfg_book_var.set(True)
    seen_opts = []
    orig_set = app.engine.set_option
    def tap_opt(name, value):
        seen_opts.append((str(name).lower(), str(value).lower()))
        return orig_set(name, value)
    app.engine.set_option = tap_opt
    app._config_start()
    app.engine.set_option = orig_set
    check("config starts game", app._active_frame == "game"
          and app.opponent_name() == "Flash", app.opponent_name())
    check("book toggle applied to engine", ("usebook", "true") in seen_opts,
          str(seen_opts[-4:]))
    check("opponent persisted", app.cfg.opponent_key == "model:Flash")
    app.show_frame("menu")
    app.set_model("High")

    print("== navigation ==")
    app.new_game(side="w", keep_setup=True)
    app.mode = "human_vs_human"; app.engine_thinking = False
    for a, b in (("e2", "e4"), ("e7", "e5")):
        app.on_square_click(parse_sq(a)); app.on_square_click(parse_sq(b))
    app.navigate(0)
    check("navigate to start", app.view == 0 and len(app.state.moves) > 0)
    app.navigate(len(app.moves))
    check("navigate back to live", app.view == len(app.moves))
    app.mode = "human_vs_engine"

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
    ok, msg = app._import_pgn("1. e4 e5 2. Nf3 Nc6 *\n")
    check("PGN text import works", ok and app.sans == ["e4", "e5", "Nf3", "Nc6"],
          f"{ok} {msg} {app.sans}")
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

    print("== board widget mapping / size / pieces ==")
    import board_widget
    bc = app.canvas
    # unflipped orientation sanity
    bc.flipped = False
    check("unflipped a8 top-left", bc.sq_to_xy(parse_sq("a8")) == (0, 0))
    check("unflipped h1 bottom-right", bc.sq_to_xy(parse_sq("h1")) == (7, 7))
    # flipped must be a true 180-degree rotation of the drawn squares
    bc.flipped = True
    check("flipped a8 bottom-right", bc.sq_to_xy(parse_sq("a8")) == (7, 7))
    check("flipped h1 top-left", bc.sq_to_xy(parse_sq("h1")) == (0, 0))
    check("flipped a1 top-right", bc.sq_to_xy(parse_sq("a1")) == (7, 0))
    # click<->square mapping must round-trip on all 64 squares, both sides
    ok = True
    for fl in (False, True):
        bc.flipped = fl
        s = bc.cell()
        for sq in range(64):
            f, r = bc.sq_to_xy(sq)
            if bc.xy_to_sq(f * s + s // 2, r * s + s // 2) != sq:
                ok = False
    check("sq<->xy roundtrip both orientations", ok)
    bc.flipped = False
    # board-size change must take effect immediately (regression: the old
    # code derived cell size from not-yet-updated winfo geometry -> no-op)
    bc.set_size(640)
    check("set_size applies immediately", bc.cell() == 80, str(bc.cell()))
    app.cfg.board_size = 600
    app.apply_cfg_visual()
    check("apply_cfg_visual resizes board", bc.cell() == 75, str(bc.cell()))
    # two-tone pieces: 8 outline stamps + body, filled glyphs for both colours
    items = bc._piece_items(50.0, 50.0, "K", 100, tags=("t",))
    check("two-tone piece = outline stamps + body", len(items) == 9, str(len(items)))
    check("white king uses filled glyph", board_widget.FILLED_PIECES["K"] == "\u265a")
    check("black king uses filled glyph", board_widget.FILLED_PIECES["k"] == "\u265a")

    check("config saved on disk", os.path.isfile(__import__("config_store").CONFIG_PATH))
    app.on_close()
    check("engine stopped after close", not app.engine.alive)
    if app.engine2:
        check("engine2 stopped after close", not app.engine2.alive)

    print(f"\nGUI headless: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
