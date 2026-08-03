def up(conn):
    """Drop the legacy REAL columns from the financials table."""
    conn.execute("DROP VIEW IF EXISTS financial_delta_view;")
    conn.execute("ALTER TABLE financials DROP COLUMN revenue;")
    conn.execute("ALTER TABLE financials DROP COLUMN carrier_rcv;")
    conn.execute("ALTER TABLE financials DROP COLUMN material_cost;")
    conn.execute("ALTER TABLE financials DROP COLUMN labor_cost;")
    conn.execute("ALTER TABLE financials DROP COLUMN permits_fee;")
    conn.execute('''
        CREATE VIEW financial_delta_view AS
            SELECT 
                j.id as job_id,
                j.homeowner_name,
                f.carrier_initial_rcv_cents,
                f.carrier_supplemented_rcv_cents,
                f.revenue_cents,
                (f.carrier_supplemented_rcv_cents - f.carrier_initial_rcv_cents) AS carrier_rcv_delta_cents,
                (f.revenue_cents - f.carrier_supplemented_rcv_cents) AS contractor_over_carrier_cents
            FROM jobs j
            JOIN financials f ON j.id = f.job_id
    ''')
