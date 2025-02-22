import time
from io import BytesIO
from typing import Any, cast

import aleo_explorer_rust
from starlette.exceptions import HTTPException
from starlette.requests import Request

from aleo_types import PlaintextValue, LiteralPlaintext, Literal, \
    Address, Value, StructPlaintext
from db import Database
from .template import templates
from .utils import out_of_sync_check


async def calc_route(request: Request):
    db: Database = request.app.state.db
    is_htmx = request.scope["htmx"].is_htmx()
    if is_htmx:
        template = "htmx/calc.jinja2"
    else:
        template = "calc.jinja2"
    proof_target = (await db.get_latest_block()).header.metadata.proof_target
    sync_info = await out_of_sync_check(db)
    ctx = {
        "request": request,
        "proof_target": proof_target,
        "sync_info": sync_info,
    }
    return templates.TemplateResponse(template, ctx, headers={'Cache-Control': 'public, max-age=60'}) # type: ignore



async def leaderboard_route(request: Request):
    db: Database = request.app.state.db
    is_htmx = request.scope["htmx"].is_htmx()
    if is_htmx:
        template = "htmx/leaderboard.jinja2"
    else:
        template = "leaderboard.jinja2"
    try:
        page = request.query_params.get("p")
        if page is None:
            page = 1
        else:
            page = int(page)
    except:
        raise HTTPException(status_code=400, detail="Invalid page")
    address_count = await db.get_leaderboard_size()
    total_pages = (address_count // 50) + 1
    if page < 1 or page > total_pages:
        raise HTTPException(status_code=400, detail="Invalid page")
    start = 50 * (page - 1)
    leaderboard_data = await db.get_leaderboard(start, start + 50)
    data: list[dict[str, Any]] = []
    for line in leaderboard_data:
        data.append({
            "address": line["address"],
            "total_rewards": line["total_reward"],
            "total_incentive": line["total_incentive"],
        })
    now = int(time.time())
    total_credit = await db.get_leaderboard_total()
    target_credit = 37_500_000_000_000
    ratio = total_credit / target_credit * 100
    sync_info = await out_of_sync_check(db)
    ctx = {
        "request": request,
        "leaderboard": data,
        "page": page,
        "total_pages": total_pages,
        "total_credit": total_credit,
        "target_credit": target_credit,
        "ratio": ratio,
        "now": now,
        "sync_info": sync_info,
    }
    return templates.TemplateResponse(template, ctx, headers={'Cache-Control': 'public, max-age=15'}) # type: ignore


async def address_route(request: Request):
    db: Database = request.app.state.db
    is_htmx = request.scope["htmx"].is_htmx()
    if is_htmx:
        template = "htmx/address.jinja2"
    else:
        template = "address.jinja2"
    address = request.query_params.get("a")
    if not address:
        raise HTTPException(status_code=400, detail="Missing address")
    solutions = await db.get_recent_solutions_by_address(address)
    programs = await db.get_recent_programs_by_address(address)
    transitions = await db.get_address_recent_transitions(address)
    address_key = LiteralPlaintext(
        literal=Literal(
            type_=Literal.Type.Address,
            primitive=Address.loads(address),
        )
    )
    address_key_bytes = address_key.dump()
    account_key_id = aleo_explorer_rust.get_key_id("credits.aleo", "account", address_key_bytes)
    bonded_key_id = aleo_explorer_rust.get_key_id("credits.aleo", "bonded", address_key_bytes)
    unbonded_key_id = aleo_explorer_rust.get_key_id("credits.aleo", "unbonded", address_key_bytes)
    committee_key_id = aleo_explorer_rust.get_key_id("credits.aleo", "committee", address_key_bytes)
    public_balance_bytes = await db.get_mapping_value("credits.aleo", "account", account_key_id)
    bond_state_bytes = await db.get_mapping_value("credits.aleo", "bonded", bonded_key_id)
    unbond_state_bytes = await db.get_mapping_value("credits.aleo", "unbonded", unbonded_key_id)
    committee_state_bytes = await db.get_mapping_value("credits.aleo", "committee", committee_key_id)
    stake_reward = await db.get_address_stake_reward(address)
    transfer_in = await db.get_address_transfer_in(address)
    transfer_out = await db.get_address_transfer_out(address)
    fee = await db.get_address_total_fee(address)

    if (len(solutions) == 0
        and len(programs) == 0
        and len(transitions) == 0
        and public_balance_bytes is None
        and bond_state_bytes is None
        and unbond_state_bytes is None
        and committee_state_bytes is None
        and stake_reward is None
        and transfer_in is None
        and transfer_out is None
        and fee is None
    ):
        raise HTTPException(status_code=404, detail="Address not found")
    if len(solutions) > 0:
        solution_count = await db.get_solution_count_by_address(address)
        total_rewards, total_incentive = await db.get_leaderboard_rewards_by_address(address)
        speed, interval = await db.get_address_speed(address)
    else:
        solution_count = 0
        total_rewards = 0
        total_incentive = 0
        speed = 0
        interval = 0
    program_count = await db.get_program_count_by_address(address)
    interval_text = {
        0: "never",
        900: "15 minutes",
        1800: "30 minutes",
        3600: "1 hour",
        14400: "4 hours",
        43200: "12 hours",
        86400: "1 day",
    }
    recent_solutions: list[dict[str, Any]] = []
    for solution in solutions:
        recent_solutions.append({
            "height": solution["height"],
            "timestamp": solution["timestamp"],
            "reward": solution["reward"],
            "nonce": solution["nonce"],
            "target": solution["target"],
            "target_sum": solution["target_sum"],
        })
    recent_programs: list[dict[str, Any]] = []
    for program in programs:
        deploy_info = await db.get_deploy_info_by_program_id(program)
        if deploy_info is None:
            raise HTTPException(status_code=550, detail="Deploy info not found")
        recent_programs.append({
            "program_id": program,
            "height": deploy_info["height"],
            "timestamp": deploy_info["timestamp"],
            "transaction_id": deploy_info["transaction_id"],
        })
    if public_balance_bytes is None:
        public_balance = 0
    else:
        value = cast(PlaintextValue, Value.load(BytesIO(public_balance_bytes)))
        plaintext = cast(LiteralPlaintext, value.plaintext)
        public_balance = int(plaintext.literal.primitive)
    if bond_state_bytes is None:
        bond_state = None
    else:
        value = cast(PlaintextValue, Value.load(BytesIO(bond_state_bytes)))
        plaintext = cast(StructPlaintext, value.plaintext)
        validator = cast(LiteralPlaintext, plaintext["validator"])
        amount = cast(LiteralPlaintext, plaintext["microcredits"])
        bond_state = {
            "validator": str(validator.literal.primitive),
            "amount": int(amount.literal.primitive),
        }
    if unbond_state_bytes is None:
        unbond_state = None
    else:
        value = cast(PlaintextValue, Value.load(BytesIO(unbond_state_bytes)))
        plaintext = cast(StructPlaintext, value.plaintext)
        amount = cast(LiteralPlaintext, plaintext["microcredits"])
        height = cast(LiteralPlaintext, plaintext["height"])
        unbond_state = {
            "amount": int(amount.literal.primitive),
            "height": str(height.literal.primitive),
        }
    if committee_state_bytes is None:
        committee_state = None
    else:
        value = cast(PlaintextValue, Value.load(BytesIO(committee_state_bytes)))
        plaintext = cast(StructPlaintext, value.plaintext)
        amount = cast(LiteralPlaintext, plaintext["microcredits"])
        is_open = cast(LiteralPlaintext, plaintext["is_open"])
        committee_state = {
            "amount": int(amount.literal.primitive),
            "is_open": bool(is_open.literal.primitive),
        }
    if stake_reward is None:
        stake_reward = 0
    if transfer_in is None:
        transfer_in = 0
    if transfer_out is None:
        transfer_out = 0
    if fee is None:
        fee = 0

    recent_transitions: list[dict[str, Any]] = []
    for transition_data in transitions:
        transition = await db.get_transition(transition_data["transition_id"])
        if transition is None:
            raise HTTPException(status_code=550, detail="Transition not found")
        recent_transitions.append({
            "transition_id": transition_data["transition_id"],
            "height": transition_data["height"],
            "timestamp": transition_data["timestamp"],
            "program_id": transition.program_id,
            "function_name": transition.function_name,
        })

    sync_info = await out_of_sync_check(db)
    ctx = {
        "request": request,
        "address": address,
        "address_trunc": address[:14] + "..." + address[-6:],
        "solutions": recent_solutions,
        "programs": recent_programs,
        "total_rewards": total_rewards,
        "total_incentive": total_incentive,
        "total_solutions": solution_count,
        "total_programs": program_count,
        "speed": speed,
        "timespan": interval_text[interval],
        "public_balance": public_balance,
        "bond_state": bond_state,
        "unbond_state": unbond_state,
        "committee_state": committee_state,
        "stake_reward": stake_reward,
        "transfer_in": transfer_in,
        "transfer_out": transfer_out,
        "fee": fee,
        "transitions": recent_transitions,
        "sync_info": sync_info,
    }
    return templates.TemplateResponse(template, ctx, headers={'Cache-Control': 'public, max-age=15'}) # type: ignore


async def address_solution_route(request: Request):
    db: Database = request.app.state.db
    is_htmx = request.scope["htmx"].is_htmx()
    if is_htmx:
        template = "htmx/address_solution.jinja2"
    else:
        template = "address_solution.jinja2"
    address = request.query_params.get("a")
    if address is None:
        raise HTTPException(status_code=400, detail="Missing address")
    try:
        page = request.query_params.get("p")
        if page is None:
            page = 1
        else:
            page = int(page)
    except:
        raise HTTPException(status_code=400, detail="Invalid page")
    solution_count = await db.get_solution_count_by_address(address)
    total_pages = (solution_count // 50) + 1
    if page < 1 or page > total_pages:
        raise HTTPException(status_code=400, detail="Invalid page")
    start = 50 * (page - 1)
    solutions = await db.get_solution_by_address(address, start, start + 50)
    data: list[dict[str, Any]] = []
    for solution in solutions:
        data.append({
            "height": solution["height"],
            "timestamp": solution["timestamp"],
            "reward": solution["reward"],
            "nonce": solution["nonce"],
            "target": solution["target"],
            "target_sum": solution["target_sum"],
        })
    sync_info = await out_of_sync_check(db)
    ctx = {
        "request": request,
        "address": address,
        "address_trunc": address[:14] + "..." + address[-6:],
        "solutions": data,
        "page": page,
        "total_pages": total_pages,
        "sync_info": sync_info,
    }
    return templates.TemplateResponse(template, ctx, headers={'Cache-Control': 'public, max-age=15'}) # type: ignore