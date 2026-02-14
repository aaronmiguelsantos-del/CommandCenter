from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.models import EventRecord, SystemContract
from core.recommendations import rag_from_score, recommend_fixes
from core.scoring import score_health
from core.storage import append_log, ensure_dirs, load_contracts, load_logs, save_contract

APL_PRIMITIVES = [
    "P0 System Contract",
    "P1 Invariant Registry",
    "P2 Schema Registry",
    "P3 Decision Engine",
    "P4 Scoring Engine",
    "P5 Trigger & Alert Engine",
    "P6 Failure Mode Library",
    "P7 State & Audit Log",
    "P8 Diff & Versioning",
]

st.set_page_config(page_title="Atlas Architecture Health", layout="wide")
ensure_dirs()

st.title("Atlas Architecture: Primitive Layer + Meta-Health Dashboard")

# Sidebar: Add / update a system contract
st.sidebar.header("Add / Update System")
with st.sidebar.form("contract_form"):
    system_id = st.text_input("system_id", value="example_system")
    name = st.text_input("name", value="Example System")
    version = st.text_input("version", value="0.1.0")
    purpose = st.text_area("purpose", value="Describe what this system does and why it exists.")
    primitives_used = st.multiselect("primitives_used", APL_PRIMITIVES, default=["P0 System Contract"])
    invariants = st.text_area("invariants (one per line)", value="INV-001")
    failure_modes = st.text_area("failure_modes (one per line)", value="data_quality\nrouting_nondeterminism")
    inputs_ = st.text_area("inputs (one per line)", value="raw_input")
    outputs_ = st.text_area("outputs (one per line)", value="decision_record")
    submitted = st.form_submit_button("Save Contract")

if submitted:
    contract = SystemContract(
        system_id=system_id.strip(),
        name=name.strip(),
        version=version.strip(),
        purpose=purpose.strip(),
        inputs=[x.strip() for x in inputs_.splitlines() if x.strip()],
        outputs=[x.strip() for x in outputs_.splitlines() if x.strip()],
        primitives_used=primitives_used,
        invariants=[x.strip() for x in invariants.splitlines() if x.strip()],
        failure_modes=[x.strip() for x in failure_modes.splitlines() if x.strip()],
        updated_at=datetime.utcnow(),
    )
    save_contract(contract)
    append_log(
        contract.system_id,
        EventRecord(system_id=contract.system_id, event_type="contract_saved", payload={"version": contract.version}),
    )
    st.sidebar.success("Saved.")

# Main: Load data
contracts = load_contracts(SystemContract)
logs_by_system = {c.system_id: len(load_logs(c.system_id)) for c in contracts}

overall, dim, issues = score_health(contracts, logs_by_system)
rag = rag_from_score(overall)
fixes = recommend_fixes(overall, dim, issues, contracts)

# Top KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall Health Score", f"{overall}/100")
c2.metric("Status", rag.upper())
c3.metric("Systems", str(len(contracts)))
c4.metric("Total Log Events", str(sum(logs_by_system.values())))

# Dimension table
st.subheader("Dimension Scores")
df_dim = pd.DataFrame([dim]).T.reset_index()
df_dim.columns = ["Dimension", "Score"]
st.dataframe(df_dim, use_container_width=True, hide_index=True)

# Contracts view
st.subheader("Systems")
if contracts:
    df = pd.DataFrame(
        [
            {
                "system_id": c.system_id,
                "name": c.name,
                "version": c.version,
                "primitives_used": len(set(c.primitives_used)),
                "invariants": len(c.invariants),
                "failure_modes": len(c.failure_modes),
                "log_events": logs_by_system.get(c.system_id, 0),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in contracts
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No contracts yet. Create one in the sidebar.")

# Issues & fixes
left, right = st.columns(2)
with left:
    st.subheader("Key Issues")
    if issues:
        for i in issues[:12]:
            st.write(f"- {i}")
    else:
        st.write("- None detected.")
with right:
    st.subheader("Recommended Fixes")
    for f in fixes:
        st.write(f"- {f}")

st.caption("v1.0 baseline. Next upgrade: invariant test execution + duplication detection via graph clustering.")
