"""trmsg - Game Engine (TicTacToe, Chess, Quiz, Leaderboard)"""
import json
import random
from typing import Optional, List, Tuple

# ── TICTACTOE ─────────────────────────────────────────────────────
def ttt_new_board() -> dict:
    return {"board": [" "] * 9, "turn": "X", "status": "active", "winner": None}

def ttt_render(board: list) -> str:
    b = board
    rows = []
    for i in range(0, 9, 3):
        rows.append(f" {b[i]} │ {b[i+1]} │ {b[i+2]} ")
    return "\n───┼───┼───\n".join(rows)

def ttt_move(state: dict, pos: int, symbol: str) -> Tuple[dict, str]:
    board = state["board"]
    if pos < 0 or pos > 8:
        return state, "Invalid position! Use 1-9"
    if board[pos] != " ":
        return state, "Cell already taken!"
    board[pos] = symbol
    winner = ttt_check_winner(board)
    if winner:
        state["status"] = "finished"
        state["winner"] = winner
    elif " " not in board:
        state["status"] = "draw"
    else:
        state["turn"] = "O" if symbol == "X" else "X"
    return state, "ok"

def ttt_check_winner(board: list) -> Optional[str]:
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in wins:
        if board[a] == board[b] == board[c] != " ":
            return board[a]
    return None

def ttt_ai_move(board: list) -> int:
    """Simple minimax AI for TicTacToe"""
    def minimax(b, is_max):
        w = ttt_check_winner(b)
        if w == "O": return 10
        if w == "X": return -10
        if " " not in b: return 0
        scores = []
        for i in range(9):
            if b[i] == " ":
                b[i] = "O" if is_max else "X"
                scores.append(minimax(b, not is_max))
                b[i] = " "
        return max(scores) if is_max else min(scores)

    best_score = -999
    best_move = 0
    for i in range(9):
        if board[i] == " ":
            board[i] = "O"
            score = minimax(board, False)
            board[i] = " "
            if score > best_score:
                best_score = score
                best_move = i
    return best_move


# ── CHESS (Simplified - display only, legal move checking) ────────
CHESS_PIECES = {
    "wK":"♔","wQ":"♕","wR":"♖","wB":"♗","wN":"♘","wP":"♙",
    "bK":"♚","bQ":"♛","bR":"♜","bB":"♝","bN":"♞","bP":"♟",
    ".":"·",
}

def chess_new_board() -> dict:
    board = [
        ["bR","bN","bB","bQ","bK","bB","bN","bR"],
        ["bP","bP","bP","bP","bP","bP","bP","bP"],
        [".",".",".",".",".",".",".","."  ],
        [".",".",".",".",".",".",".","."  ],
        [".",".",".",".",".",".",".","."  ],
        [".",".",".",".",".",".",".","."  ],
        ["wP","wP","wP","wP","wP","wP","wP","wP"],
        ["wR","wN","wB","wQ","wK","wB","wN","wR"],
    ]
    return {"board": board, "turn": "w", "status": "active", "winner": None, "moves": []}

def chess_render(board: list) -> str:
    lines = ["  a b c d e f g h"]
    for i, row in enumerate(board):
        rank = 8 - i
        cells = " ".join(CHESS_PIECES.get(p, p) for p in row)
        lines.append(f"{rank} {cells} {rank}")
    lines.append("  a b c d e f g h")
    return "\n".join(lines)

def chess_parse_move(move_str: str) -> Optional[Tuple]:
    """Parse algebraic notation e2e4 → ((6,4),(4,4))"""
    move_str = move_str.strip().lower()
    if len(move_str) != 4:
        return None
    try:
        cols = "abcdefgh"
        fc, fr, tc, tr = move_str[0], move_str[1], move_str[2], move_str[3]
        from_col = cols.index(fc)
        from_row = 8 - int(fr)
        to_col = cols.index(tc)
        to_row = 8 - int(tr)
        return (from_row, from_col), (to_row, to_col)
    except:
        return None

def chess_make_move(state: dict, move_str: str, player_color: str) -> Tuple[dict, str]:
    parsed = chess_parse_move(move_str)
    if not parsed:
        return state, "Invalid move format. Use e2e4 style"
    (fr, fc), (tr, tc) = parsed
    board = state["board"]
    piece = board[fr][fc]
    if piece == "." or not piece.startswith(player_color):
        return state, f"No {player_color} piece at that position"
    board[tr][tc] = piece
    board[fr][fc] = "."
    state["moves"].append(move_str)
    state["turn"] = "b" if player_color == "w" else "w"
    # Check if king captured (simplified win condition)
    flat = [p for row in board for p in row]
    if "wK" not in flat:
        state["status"] = "finished"
        state["winner"] = "b"
    elif "bK" not in flat:
        state["status"] = "finished"
        state["winner"] = "w"
    return state, "ok"


# ── QUIZ ──────────────────────────────────────────────────────────
QUIZ_QUESTIONS = [
    {"q": "What does CPU stand for?", "options": ["A. Central Processing Unit", "B. Computer Personal Unit", "C. Core Processing Utility", "D. Central Program Unit"], "answer": "A", "points": 10},
    {"q": "Which language is Python named after?", "options": ["A. A snake", "B. Monty Python", "C. A Greek god", "D. A scientist"], "answer": "B", "points": 10},
    {"q": "What is 2^10?", "options": ["A. 512", "B. 1024", "C. 2048", "D. 256"], "answer": "B", "points": 10},
    {"q": "Who created Linux?", "options": ["A. Bill Gates", "B. Steve Jobs", "C. Linus Torvalds", "D. Dennis Ritchie"], "answer": "C", "points": 10},
    {"q": "What does HTTP stand for?", "options": ["A. HyperText Transfer Protocol", "B. High Tech Transfer Page", "C. HyperText Transmission Program", "D. None of above"], "answer": "A", "points": 10},
    {"q": "Which port does HTTPS use by default?", "options": ["A. 80", "B. 21", "C. 443", "D. 8080"], "answer": "C", "points": 10},
    {"q": "What is the time complexity of binary search?", "options": ["A. O(n)", "B. O(n²)", "C. O(log n)", "D. O(1)"], "answer": "C", "points": 15},
    {"q": "What does SQL stand for?", "options": ["A. Structured Query Language", "B. Simple Question Language", "C. System Query Logic", "D. Structured Question Logic"], "answer": "A", "points": 10},
    {"q": "Which data structure uses LIFO?", "options": ["A. Queue", "B. Stack", "C. Tree", "D. Graph"], "answer": "B", "points": 10},
    {"q": "What is Git used for?", "options": ["A. Database management", "B. Version control", "C. Web hosting", "D. Code compilation"], "answer": "B", "points": 10},
    {"q": "What does API stand for?", "options": ["A. App Programming Interface", "B. Application Protocol Integration", "C. Application Programming Interface", "D. Auto Program Interface"], "answer": "C", "points": 10},
    {"q": "Which symbol starts a comment in Python?", "options": ["A. //", "B. /*", "C. #", "D. --"], "answer": "C", "points": 10},
    {"q": "What is localhost?", "options": ["A. A web server", "B. Your own computer", "C. Google's server", "D. A database"], "answer": "B", "points": 10},
    {"q": "What is a NULL value in databases?", "options": ["A. Zero", "B. Empty string", "C. Unknown/missing value", "D. False"], "answer": "C", "points": 15},
    {"q": "WebSocket protocol starts with?", "options": ["A. http://", "B. ftp://", "C. ws://", "D. tcp://"], "answer": "C", "points": 15},
]

def quiz_new_game(num_questions: int = 5) -> dict:
    questions = random.sample(QUIZ_QUESTIONS, min(num_questions, len(QUIZ_QUESTIONS)))
    return {
        "questions": questions,
        "current": 0,
        "scores": {},
        "answered": {},
        "status": "active",
    }

def quiz_answer(state: dict, user: str, answer: str) -> Tuple[dict, str, int]:
    idx = state["current"]
    if idx >= len(state["questions"]):
        return state, "Quiz is over!", 0
    if f"{idx}_{user}" in state["answered"]:
        return state, "Already answered this question!", 0
    q = state["questions"][idx]
    correct = answer.upper().strip() == q["answer"]
    points = q["points"] if correct else 0
    state["scores"][user] = state["scores"].get(user, 0) + points
    state["answered"][f"{idx}_{user}"] = answer.upper()
    msg = f"✅ Correct! +{points} points" if correct else f"❌ Wrong! Answer was {q['answer']}"
    return state, msg, points

def quiz_next_question(state: dict) -> Tuple[dict, Optional[dict]]:
    state["current"] += 1
    if state["current"] >= len(state["questions"]):
        state["status"] = "finished"
        return state, None
    return state, state["questions"][state["current"]]

def quiz_render_question(q: dict, num: int, total: int) -> str:
    lines = [f"❓ Question {num}/{total}: {q['q']}"]
    lines.extend(q["options"])
    lines.append("Reply: /answer A  or  /answer B  etc.")
    return "\n".join(lines)

def quiz_render_scores(scores: dict) -> str:
    if not scores:
        return "No scores yet"
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    lines = ["🏆 Scores:"]
    medals = ["🥇","🥈","🥉"]
    for i, (user, score) in enumerate(sorted_scores):
        medal = medals[i] if i < 3 else f"#{i+1}"
        lines.append(f"  {medal} {user}: {score} pts")
    return "\n".join(lines)
