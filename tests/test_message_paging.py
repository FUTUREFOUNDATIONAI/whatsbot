"""History paging: cursor correctness, jump-to-message, quoted originals, legacy shape.

Runs against a temporary SQLite database (GOWA and the LLM are never touched).

    python tests/test_message_paging.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_tmpdir = tempfile.mkdtemp(prefix="whatsbot_paging_")
from db import init_db  # noqa: E402

init_db(Path(_tmpdir) / "whatsbot.db")

from db.repositories import contact_repo, message_repo, tag_repo  # noqa: E402
from sqlalchemy import event  # noqa: E402
from db.engine import get_engine  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK {name}")
    else:
        failed += 1
        print(f"  FAIL {name}" + (f" -- {detail}" if detail else ""))


def ids(page):
    return [m["_id"] for m in page["messages"]]


# ── fixture: 250 messages, three of them sharing one timestamp ──────────
contact = contact_repo.get_or_create("5511999990100")
cid = contact["id"]
base = time.time() - 10_000
added = []
for i in range(250):
    ts = base + i
    if i in (120, 121, 122):
        ts = base + 120  # identical timestamps: only the id can order them
    added.append(message_repo.add(
        cid, "user" if i % 2 == 0 else "assistant", f"msg {i}", ts=ts,
        msg_id=f"WAID{i}",
        reply_to_msg_id="WAID3" if i == 200 else None))
all_ids = [m["id"] for m in added]

# a second contact must never leak into the first one's pages
other = contact_repo.get_or_create("5511999990101")
foreign = message_repo.add(other["id"], "user", "other chat", ts=base + 50)

print("\n-- newest page")
p = message_repo.get_page(cid, 50)
check("newest page has 50 messages", len(p["messages"]) == 50)
check("newest page ends at the last message", ids(p)[-1] == all_ids[-1])
check("newest page is ascending", ids(p) == sorted(ids(p)))
check("older messages remain", p["has_more_before"] is True)
check("no newer messages at the live edge", p["has_more_after"] is False)

print("\n-- walking backwards covers everything exactly once")
seen = []
page = message_repo.get_page(cid, 40)
seen = ids(page) + seen
guard = 0
while page["has_more_before"] and guard < 20:
    page = message_repo.get_page(cid, 40, before=ids(page)[0])
    seen = ids(page) + seen
    guard += 1
check("every message visited", sorted(seen) == sorted(all_ids), f"{len(seen)} vs {len(all_ids)}")
check("no duplicates walking back", len(seen) == len(set(seen)))
check("order preserved", seen == all_ids)
check("foreign message never appears", foreign["id"] not in seen)

print("\n-- shared timestamps are neither skipped nor repeated")
tie = [all_ids[120], all_ids[121], all_ids[122]]
for size in (1, 2, 3, 7):
    walked = []
    page = message_repo.get_page(cid, size, before=all_ids[130])
    walked = ids(page) + walked
    while page["has_more_before"]:
        page = message_repo.get_page(cid, size, before=ids(page)[0])
        walked = ids(page) + walked
    check(f"page size {size}: all ids before cursor once",
          walked == all_ids[:130], f"{len(walked)}")
    forward = []
    page = message_repo.get_page(cid, size, after=all_ids[118])
    forward += ids(page)
    while page["has_more_after"]:
        page = message_repo.get_page(cid, size, after=ids(page)[-1])
        forward += ids(page)
    check(f"page size {size}: forward walk keeps the tied trio in order",
          forward == all_ids[119:], f"{len(forward)}")
check("tied trio ordered by id", [i for i in message_repo.get_all(cid) if False] == [] and
      [m["_id"] for m in message_repo.get_all(cid)][120:123] == tie)

print("\n-- around")
p = message_repo.get_page(cid, 20, around=all_ids[100])
check("around contains the target", all_ids[100] in ids(p))
check("around is centered", ids(p).index(all_ids[100]) in range(8, 13), str(ids(p).index(all_ids[100])))
check("around: older exist", p["has_more_before"] is True)
check("around: newer exist", p["has_more_after"] is True)
check("around is ascending and contiguous", ids(p) == all_ids[all_ids.index(ids(p)[0]):all_ids.index(ids(p)[0]) + len(ids(p))])
p = message_repo.get_page(cid, 20, around=all_ids[0])
check("around the very first message: nothing older", p["has_more_before"] is False and ids(p)[0] == all_ids[0])
p = message_repo.get_page(cid, 20, around=all_ids[-1])
check("around the last message: nothing newer", p["has_more_after"] is False and ids(p)[-1] == all_ids[-1])
p = message_repo.get_page(cid, 20, around=foreign["id"])
check("around another contact's message -> not found", p["found"] is False)
p = message_repo.get_page(cid, 20, before=foreign["id"])
check("before another contact's message -> not found", p["found"] is False)
p = message_repo.get_page(cid, 20, after=999_999_999)
check("unknown cursor -> not found", p["found"] is False)

print("\n-- quoted originals outside the window")
page = message_repo.get_page(cid, 60)  # newest 60 = msgs 190..249: has the reply (200), not msg 3
quoted = message_repo.get_quoted(cid, page["messages"])
check("reply present in window", any(m.get("reply_to_msg_id") == "WAID3" for m in page["messages"]))
check("original outside the window is returned", "WAID3" in quoted and quoted["WAID3"]["content"] == "msg 3")
page = message_repo.get_page(cid, 400)
check("no extras when the original is already in the window", message_repo.get_quoted(cid, page["messages"]) == {})
check("find_id_by_msg_id resolves", message_repo.find_id_by_msg_id(cid, "WAID3") == all_ids[3])
check("find_id_by_msg_id ignores other contacts",
      message_repo.find_id_by_msg_id(other["id"], "WAID3") is None)

print("\n-- list_contacts tag query is batched")
tag_repo.create("alpha", "#111111")
tag_repo.create("beta", "#222222")
tag_repo.add_contact_tag(cid, "beta")
tag_repo.add_contact_tag(cid, "alpha")
for n in range(30):
    c = contact_repo.get_or_create(f"55119999902{n:02d}")
    if n % 3 == 0:
        tag_repo.add_contact_tag(c["id"], "alpha")
statements = []
engine = get_engine()


def _count(conn, cursor, statement, *a):
    statements.append(statement)


event.listen(engine, "before_cursor_execute", _count)
rows = contact_repo.list_contacts()
event.remove(engine, "before_cursor_execute", _count)
check("list uses a constant number of queries", len(statements) <= 3, f"{len(statements)} queries for {len(rows)} contacts")
mine = next(r for r in rows if r["id"] == cid)
check("tags preserved and ordered by tag id", mine["tags"] == ["alpha", "beta"], str(mine["tags"]))
check("contact without tags gets an empty list", all("tags" in r and isinstance(r["tags"], list) for r in rows))

print("\n-- HTTP: legacy shape and paged shape")
from starlette.testclient import TestClient  # noqa: E402
from config.settings import Settings  # noqa: E402
from agent.handler import AgentHandler  # noqa: E402
from server.app import create_app  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

gowa_client = MagicMock()
gowa_client.can_bot_send_in_group = MagicMock(return_value=True)
app = create_app(
    settings=Settings(),
    gowa_manager=MagicMock(),
    gowa_client=gowa_client,
    agent_handler=AgentHandler(api_key="x", system_prompt="t", max_context_messages=10, model="m"),
)


@asynccontextmanager
async def _noop(app):
    yield


app.router.lifespan_context = _noop
client = TestClient(app, raise_server_exceptions=False)

r = client.get(f"/api/contacts/{contact['phone']}?mark_read=false")
d = r.json()["data"]
check("legacy GET returns the whole history", len(d["messages"]) == 250)
check("legacy GET reports nothing more to load", d["has_more_before"] is False and d["has_more_after"] is False)

r = client.get(f"/api/contacts/{contact['phone']}?mark_read=false&limit=60")
d = r.json()["data"]
check("paged GET returns the newest 60", len(d["messages"]) == 60 and d["messages"][-1]["_id"] == all_ids[-1])
check("paged GET flags older history", d["has_more_before"] is True and d["has_more_after"] is False)
check("paged GET carries quoted originals as a map", isinstance(d["quoted"], dict))

r = client.get(f"/api/contacts/{contact['phone']}?mark_read=false&limit=60&around={all_ids[50]}")
d = r.json()["data"]
check("GET around opens on the target", any(m["_id"] == all_ids[50] for m in d["messages"]))
check("GET around flags both directions", d["has_more_before"] and d["has_more_after"])
r = client.get(f"/api/contacts/{contact['phone']}?mark_read=false&limit=60&around={foreign['id']}")
d = r.json()["data"]
check("GET around a foreign id falls back to the newest page", d["messages"][-1]["_id"] == all_ids[-1])
r = client.get(f"/api/contacts/{contact['phone']}?mark_read=false&limit=100000")
check("limit is capped", len(r.json()["data"]["messages"]) <= 300)

phone = contact["phone"]
first = message_repo.get_page(cid, 60)["messages"][0]["_id"]
r = client.get(f"/api/contacts/{phone}/messages?before={first}&limit=30")
d = r.json()["data"]
check("messages endpoint: older page", r.status_code == 200 and len(d["messages"]) == 30 and d["messages"][-1]["_id"] == all_ids[all_ids.index(first) - 1])
r = client.get(f"/api/contacts/{phone}/messages?after={all_ids[-5]}")
d = r.json()["data"]
check("messages endpoint: newer page", [m["_id"] for m in d["messages"]] == all_ids[-4:] and d["has_more_after"] is False)
r = client.get(f"/api/contacts/{phone}/messages?before=1&after=2")
check("messages endpoint: cursors are mutually exclusive", r.status_code == 400)
r = client.get(f"/api/contacts/{phone}/messages?before={foreign['id']}")
check("messages endpoint: foreign cursor -> 404", r.status_code == 404)
r = client.get("/api/contacts/5599000000000/messages")
check("messages endpoint: unknown contact -> 404 and no contact created",
      r.status_code == 404 and contact_repo.get_by_phone("5599000000000") is None)

print("\n-- group permission check")
import asyncio  # noqa: E402
import httpx  # noqa: E402
import server.routes.contacts as contacts_routes  # noqa: E402

group = contact_repo.get_or_create("120363000000000001@g.us")
contact_repo.update(group["id"], is_group=1)

# The route reads state.bot_phone; find the AppState it closed over.
closure_state = None
for route in app.routes:
    if getattr(route, "path", "") == "/api/contacts/{phone}":
        for cell in (route.endpoint.__closure__ or ()):
            try:
                v = cell.cell_contents
            except ValueError:
                continue
            if v.__class__.__name__ == "AppState":
                closure_state = v
        break
check("app state reachable for the group test", closure_state is not None)


async def _open_group():
    """Open the group once through the ASGI app inside a single event loop and
    return (response, seconds). Unlike TestClient (one loop per request, whose
    teardown joins any still-sleeping worker thread) this measures what the
    handler itself takes, i.e. what a user waits for."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        t = time.perf_counter()
        r = await ac.get(f"/api/contacts/{group['phone']}?mark_read=false&limit=50")
        return r, time.perf_counter() - t


if closure_state is not None:
    closure_state.bot_phone = "5511000000000"

    contacts_routes._can_send_cache.clear()
    contacts_routes._can_send_failed_at.clear()
    gowa_client.can_bot_send_in_group.reset_mock()
    gowa_client.can_bot_send_in_group.side_effect = None
    gowa_client.can_bot_send_in_group.return_value = False
    r1, _ = asyncio.run(_open_group())
    r2, _ = asyncio.run(_open_group())
    check("group can_send reflects GOWA", r1.json()["data"]["can_send"] is False)
    check("permission lookup is cached between opens",
          gowa_client.can_bot_send_in_group.call_count == 1,
          str(gowa_client.can_bot_send_in_group.call_count))

    # A GOWA that hangs longer than the timeout must not hold the chat hostage.
    contacts_routes._can_send_cache.clear()
    contacts_routes._can_send_failed_at.clear()
    contacts_routes._CAN_SEND_TIMEOUT = 0.6
    hang = 2.5

    def _slow(*a, **k):
        time.sleep(hang)
        return True
    gowa_client.can_bot_send_in_group.side_effect = _slow
    r3, elapsed = asyncio.run(_open_group())
    check("slow GOWA: conversation still opens", r3.status_code == 200)
    check("slow GOWA: answered at the timeout, not after the hang",
          elapsed < hang - 0.8, f"{elapsed:.2f}s (hang {hang}s, timeout 0.6s)")
    check("stored permission is used when the lookup times out",
          r3.json()["data"]["can_send"] is False)

    # After a timeout GOWA is not asked again right away (no pile of blocked threads).
    calls_before = gowa_client.can_bot_send_in_group.call_count
    r3b, elapsed_b = asyncio.run(_open_group())
    check("after a failure the lookup is paused briefly",
          gowa_client.can_bot_send_in_group.call_count == calls_before and elapsed_b < 1.0,
          f"{gowa_client.can_bot_send_in_group.call_count - calls_before} extra calls, {elapsed_b:.2f}s")

    # A GOWA error must not break the open either.
    contacts_routes._can_send_cache.clear()
    contacts_routes._can_send_failed_at.clear()
    gowa_client.can_bot_send_in_group.side_effect = RuntimeError("boom")
    r4, _ = asyncio.run(_open_group())
    check("GOWA error: conversation still opens", r4.status_code == 200)
    closure_state.bot_phone = ""

print(f"\nRESULTS: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
