import os
import datetime
import json
import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Project Nexus Core Engine")

# Enable Cross-Origin Resource Sharing so our HTML dashboard can safely read/write to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the strict incoming telemetry payload matching hardware dongles
class TelemetryPayload(BaseModel):
    inverter_id: str
    installer_id: str
    battery_soc: float
    pv_power_kw: float
    load_power_kw: float
    grid_voltage: float

# Safely pull the Render internal or external database connection string
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="Database URL environment variable missing.")
    return psycopg2.connect(DATABASE_URL)

# Automatically verify and build the tables on startup so the user doesn't need database admin tools
@app.on_event("startup")
def initialize_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build core table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inverter_telemetry (
                recorded_at TIMESTAMPTZ NOT NULL,
                inverter_id VARCHAR(50) NOT NULL,
                installer_id VARCHAR(50) NOT NULL,
                battery_soc NUMERIC(5,2),       
                pv_power_kw NUMERIC(6,2),       
                load_power_kw NUMERIC(6,2),     
                grid_voltage NUMERIC(5,2),      
                PRIMARY KEY (recorded_at, inverter_id)
            );
        """)
        conn.commit()

        # Safely attempt to convert it to a TimescaleDB hypertable if Timescale is enabled
        try:
            cursor.execute("SELECT create_hypertable('inverter_telemetry', 'recorded_at', if_not_exists => TRUE);")
            conn.commit()
            print("🚀 TimescaleDB Hypertable initialized successfully.")
        except Exception:
            conn.rollback() # Rollback if TimescaleDB extension isn't loaded on standard Postgres tier
            print("ℹ️ Standard Relational Indexing applied.")

        # Create indexes for rapid multi-tenant analytics
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_installer_history ON inverter_telemetry (installer_id, recorded_at DESC);")
        conn.commit()
        
        cursor.close()
        conn.close()
        print("✅ Database Schema fully verified and initialized.")
    except Exception as e:
        print(f"❌ Database Initialization Failed: {str(e)}")

def trigger_notifications(phone: str, message: str):
    # This simulates a production-ready webhook trigger destined for our WhatsApp gateway
    print(f"\n📢 [WHATSAPP NOTIFICATION TRIGGERED] Phone: {phone}\nPayload: {message}\n")

@app.get("/")
def health_check():
    # Health route to check system status and confirm live database handshake
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        cursor.close()
        conn.close()
        return {"status": "Project Nexus Active", "database": "Connected", "timestamp": str(datetime.datetime.utcnow())}
    except Exception as e:
        return {"status": "Degraded", "database": "Disconnected", "error": str(e)}

@app.post("/telemetry")
def receive_telemetry(payload: TelemetryPayload):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Local variables
        inverter_id = payload.inverter_id
        installer_id = payload.installer_id
        battery_soc = payload.battery_soc
        pv_power_kw = payload.pv_power_kw
        load_power_kw = payload.load_power_kw
        grid_voltage = payload.grid_voltage
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Track warning states to return to the front-end dynamically
        alerts_triggered = []

        # NIGERIAN CONSTRAINT: Filter out destructive voltage surges
        original_voltage = grid_voltage
        if grid_voltage > 275.0:
            grid_voltage = 240.0  # Safe default baseline database adjustment
            alerts_triggered.append(f"SURGE: High grid input voltage ({original_voltage}V) normalized to 240V.")

        # Commit raw inverter metrics to TimescaleDB / Postgres
        cursor.execute(
            """
            INSERT INTO inverter_telemetry (recorded_at, inverter_id, installer_id, battery_soc, pv_power_kw, load_power_kw, grid_voltage)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (now, inverter_id, installer_id, battery_soc, pv_power_kw, load_power_kw, grid_voltage)
        )
        conn.commit()

        # RULE 1: THE NIGHTTIME BATTERY GUARD DOG (Targeting Off-Peak Hours 23:00 - 05:00)
        current_hour = datetime.datetime.now().hour
        is_night = (current_hour >= 23 or current_hour <= 5)
        if battery_soc < 25.0 and is_night:
            alert_msg = (
                f"🚨 *CRITICAL NEXUS ALERT* 🚨\n\n"
                f"Battery on Inverter *{inverter_id}* has dropped to a critical *{battery_soc}%*.\n"
                f"Current Load: *{load_power_kw}kW*.\n\n"
                f"Please shut down all heavy loads immediately to preserve battery lifespan!"
            )
            trigger_notifications("+2348030000000", alert_msg)
            alerts_triggered.append("CRITICAL: WhatsApp Nighttime Battery Guard triggered!")

        # RULE 2: HARMATTAN DUST DETECTION LOOPS (Targeting Peak Solar Hours 12:00 - 14:00)
        is_peak_daylight = (12 <= current_hour <= 14)
        if is_peak_daylight and pv_power_kw < 0.1:
            dust_msg = (
                f"🔧 *FLEET MAINTENANCE FLAG* 🔧\n\n"
                f"Inverter *{inverter_id}* is logging near-zero solar output ({pv_power_kw}kW) during peak afternoon hours.\n"
                f"Possible Cause: Heavy dust accumulation or physical array disruption."
            )
            trigger_notifications("+2348120000000", dust_msg)
            alerts_triggered.append("WARNING: Low solar generation detected at peak afternoon hours (Harmattan Alert).")

        cursor.close()
        conn.close()
        
        return {
            "status": "success",
            "message": "Telemetry logged safely to database",
            "voltage_surges_normalized": original_voltage > 275.0,
            "alerts": alerts_triggered
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Insertion Error: {str(e)}")

@app.get("/history")
def get_history(limit: int = 50):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Query last 50 entries
        cursor.execute(
            """
            SELECT recorded_at, inverter_id, installer_id, battery_soc, pv_power_kw, load_power_kw, grid_voltage
            FROM inverter_telemetry
            ORDER BY recorded_at DESC
            LIMIT %s;
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Parse into organized JSON dictionary payloads
        history = []
        for r in rows:
            history.append({
                "recorded_at": r[0].isoformat(),
                "inverter_id": r[1],
                "installer_id": r[2],
                "battery_soc": float(r[3]),
                "pv_power_kw": float(r[4]),
                "load_power_kw": float(r[5]),
                "grid_voltage": float(r[6])
            })
        return {"count": len(history), "data": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Retrieval Error: {str(e)}")
