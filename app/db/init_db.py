from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.models.entities import Base, ProctorDatasetSource
from app.services.account_rules import sync_existing_accounts


def _migrate_proctor_training_feedback_nullable_attempt_id(conn) -> None:
    """Allow NULL attempt_id for preview-session training labels (legacy SQLite was NOT NULL)."""
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='proctor_training_feedback'")).fetchall()
    if not rows:
        return
    cols = conn.execute(text("PRAGMA table_info(proctor_training_feedback)")).fetchall()
    att = next((r for r in cols if r[1] == "attempt_id"), None)
    if not att or int(att[3] or 0) == 0:
        return
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("DROP TABLE IF EXISTS proctor_training_feedback__mig"))
    conn.execute(
        text(
            """
            CREATE TABLE proctor_training_feedback__mig (
                id INTEGER NOT NULL PRIMARY KEY,
                attempt_id INTEGER REFERENCES exam_attempts(id),
                result_id INTEGER REFERENCES results(id),
                session_id INTEGER REFERENCES proctor_sessions(id),
                actor_user_id INTEGER NOT NULL REFERENCES users(id),
                feedback_label VARCHAR(20) NOT NULL,
                comment TEXT,
                model_decision VARCHAR(40),
                model_probability FLOAT,
                final_result_passed BOOLEAN,
                created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        ),
    )
    conn.execute(text("INSERT INTO proctor_training_feedback__mig SELECT * FROM proctor_training_feedback"))
    conn.execute(text("DROP TABLE proctor_training_feedback"))
    conn.execute(text("ALTER TABLE proctor_training_feedback__mig RENAME TO proctor_training_feedback"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proctor_training_feedback_attempt_id ON proctor_training_feedback (attempt_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proctor_training_feedback_result_id ON proctor_training_feedback (result_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proctor_training_feedback_session_id ON proctor_training_feedback (session_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proctor_training_feedback_actor_user_id ON proctor_training_feedback (actor_user_id)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))


def _sqlite_add_column_if_missing(conn, table: str, column: str, ddl_suffix: str) -> None:
    rows = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")).fetchall()
    if not rows:
        return
    cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    names = {row[1] for row in cols}
    if column in names:
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_suffix}"))


def _migrate_live_class_schema_sqlite(conn) -> None:
    # live_class_sessions incremental columns
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "timezone", "TEXT DEFAULT 'UTC'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "meeting_mode", "TEXT DEFAULT 'in_app'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "external_meeting_url", "TEXT")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "status", "TEXT DEFAULT 'scheduled'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "scheduled_start_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "scheduled_end_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "started_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "ended_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "max_participants", "INTEGER DEFAULT 200")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "allow_chat", "BOOLEAN DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "allow_raise_hand", "BOOLEAN DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "allow_reactions", "BOOLEAN DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "board_text", "TEXT")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "active_poll_key", "TEXT")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "active_poll_question", "TEXT")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "active_poll_options_json", "JSON DEFAULT '[]'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "active_poll_open", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "recurrence_pattern", "TEXT DEFAULT 'none'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "recurrence_count", "INTEGER DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "recurrence_custom_days_json", "JSON DEFAULT '[]'")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
    _sqlite_add_column_if_missing(conn, "live_class_sessions", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")

    # live_class_participants incremental columns
    _sqlite_add_column_if_missing(conn, "live_class_participants", "actor_role", "TEXT DEFAULT 'student'")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "display_name", "TEXT")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "is_present", "BOOLEAN DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "raised_hand", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "joined_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "left_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "live_class_participants", "last_seen_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")

    # live_class_messages payload field
    _sqlite_add_column_if_missing(conn, "live_class_messages", "payload_json", "JSON DEFAULT '{}'")


def _migrate_live_class_schema_postgres(conn) -> None:
    # `IF NOT EXISTS` keeps this idempotent across deploys.
    statements = [
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS timezone VARCHAR(80) DEFAULT 'UTC'",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS meeting_mode VARCHAR(20) DEFAULT 'in_app'",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS external_meeting_url VARCHAR(1000)",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'scheduled'",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS scheduled_start_at TIMESTAMPTZ",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS scheduled_end_at TIMESTAMPTZ",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS max_participants INTEGER DEFAULT 200",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS allow_chat BOOLEAN DEFAULT TRUE",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS allow_raise_hand BOOLEAN DEFAULT TRUE",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS allow_reactions BOOLEAN DEFAULT TRUE",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS board_text TEXT",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS active_poll_key VARCHAR(64)",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS active_poll_question TEXT",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS active_poll_options_json JSON DEFAULT '[]'::json",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS active_poll_open BOOLEAN DEFAULT FALSE",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS recurrence_pattern VARCHAR(20) DEFAULT 'none'",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS recurrence_count INTEGER DEFAULT 1",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS recurrence_custom_days_json JSON DEFAULT '[]'::json",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE live_class_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS actor_role VARCHAR(20) DEFAULT 'student'",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS display_name VARCHAR(200)",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS is_present BOOLEAN DEFAULT TRUE",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS raised_hand BOOLEAN DEFAULT FALSE",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS left_at TIMESTAMPTZ",
        "ALTER TABLE live_class_participants ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE live_class_messages ADD COLUMN IF NOT EXISTS payload_json JSON DEFAULT '{}'::json",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            # Keep startup resilient even on partially-migrated datasets.
            pass


def _migrate_identity_schema_sqlite(conn) -> None:
    _sqlite_add_column_if_missing(conn, "providers", "business_registration_type", "TEXT")
    _sqlite_add_column_if_missing(conn, "providers", "business_registration_number", "TEXT")
    _sqlite_add_column_if_missing(conn, "providers", "business_registration_country", "TEXT")


def _migrate_identity_schema_postgres(conn) -> None:
    statements = [
        "ALTER TABLE providers ADD COLUMN IF NOT EXISTS business_registration_type VARCHAR(40)",
        "ALTER TABLE providers ADD COLUMN IF NOT EXISTS business_registration_number VARCHAR(120)",
        "ALTER TABLE providers ADD COLUMN IF NOT EXISTS business_registration_country VARCHAR(8)",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def _migrate_stream_market_schema_sqlite(conn) -> None:
    _sqlite_add_column_if_missing(conn, "courses", "fair_usage_multiplier", "FLOAT DEFAULT 2.5")
    _sqlite_add_column_if_missing(conn, "courses", "fair_usage_override_seconds", "INTEGER")
    _sqlite_add_column_if_missing(conn, "courses", "admin_fair_usage_override_enabled", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "courses", "suitable_age_ranges", "TEXT DEFAULT '[]'")
    _sqlite_add_column_if_missing(conn, "courses", "intro_video_url", "TEXT")
    _sqlite_add_column_if_missing(conn, "courses", "preview_video_url", "TEXT")
    _sqlite_add_column_if_missing(conn, "courses", "main_video_url", "TEXT")
    _sqlite_add_column_if_missing(conn, "courses", "price_currency", "TEXT DEFAULT 'INR'")
    _sqlite_add_column_if_missing(conn, "courses", "base_price_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "courses", "gst_rate", "FLOAT DEFAULT 0.18")
    _sqlite_add_column_if_missing(conn, "courses", "platform_commission_rate", "FLOAT DEFAULT 0.25")
    _sqlite_add_column_if_missing(conn, "courses", "hosting_fee_amount", "FLOAT DEFAULT 2500")
    _sqlite_add_column_if_missing(conn, "courses", "gst_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "courses", "platform_commission_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "courses", "final_price_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "base_price_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "suitable_age_ranges", "TEXT DEFAULT '[]'")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "intro_video_url", "TEXT")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "price_currency", "TEXT DEFAULT 'INR'")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "gst_rate", "FLOAT DEFAULT 0.18")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "platform_commission_rate", "FLOAT DEFAULT 0.25")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "hosting_fee_amount", "FLOAT DEFAULT 2500")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "gst_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "platform_commission_amount", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "provider_course_drafts", "final_price_amount", "FLOAT DEFAULT 0")
    try:
        conn.execute(text("UPDATE courses SET fair_usage_multiplier = 2.5 WHERE fair_usage_multiplier IS NULL OR fair_usage_multiplier > 2.5"))
    except Exception:
        pass


def _migrate_stream_market_schema_postgres(conn) -> None:
    statements = [
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS fair_usage_multiplier FLOAT DEFAULT 2.5",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS fair_usage_override_seconds INTEGER",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS admin_fair_usage_override_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS suitable_age_ranges JSON DEFAULT '[]'::json",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS intro_video_url VARCHAR(1000)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS preview_video_url VARCHAR(1000)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS main_video_url VARCHAR(1000)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS price_currency VARCHAR(8) DEFAULT 'INR'",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS base_price_amount FLOAT DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS gst_rate FLOAT DEFAULT 0.18",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS platform_commission_rate FLOAT DEFAULT 0.25",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS hosting_fee_amount FLOAT DEFAULT 2500",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS gst_amount FLOAT DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS platform_commission_amount FLOAT DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS final_price_amount FLOAT DEFAULT 0",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS base_price_amount FLOAT DEFAULT 0",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS suitable_age_ranges JSON DEFAULT '[]'::json",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS intro_video_url VARCHAR(1000)",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS price_currency VARCHAR(8) DEFAULT 'INR'",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS gst_rate FLOAT DEFAULT 0.18",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS platform_commission_rate FLOAT DEFAULT 0.25",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS hosting_fee_amount FLOAT DEFAULT 2500",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS gst_amount FLOAT DEFAULT 0",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS platform_commission_amount FLOAT DEFAULT 0",
        "ALTER TABLE provider_course_drafts ADD COLUMN IF NOT EXISTS final_price_amount FLOAT DEFAULT 0",
        "ALTER TABLE courses ALTER COLUMN fair_usage_multiplier SET DEFAULT 2.5",
        "UPDATE courses SET fair_usage_multiplier = 2.5 WHERE fair_usage_multiplier IS NULL OR fair_usage_multiplier > 2.5",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def _migrate_exam_schema_sqlite(conn) -> None:
    _sqlite_add_column_if_missing(conn, "exams", "assessment_type", "TEXT DEFAULT 'mcq'")
    _sqlite_add_column_if_missing(conn, "exams", "instructions", "TEXT DEFAULT ''")
    _sqlite_add_column_if_missing(conn, "exams", "assessment_about", "TEXT DEFAULT ''")
    _sqlite_add_column_if_missing(conn, "exams", "tools_json", "JSON")
    _sqlite_add_column_if_missing(conn, "exams", "topics_json", "JSON")
    _sqlite_add_column_if_missing(conn, "exams", "timing_mode", "TEXT DEFAULT 'assessment'")
    _sqlite_add_column_if_missing(conn, "exams", "time_per_question_seconds", "INTEGER")
    _sqlite_add_column_if_missing(conn, "exams", "questions_per_attempt", "INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "exams", "negative_marking", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "exams", "shuffle_questions", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "exams", "shuffle_options", "BOOLEAN DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "exams", "max_attempts", "INTEGER DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "exams", "certificate_enabled", "BOOLEAN DEFAULT 1")
    _sqlite_add_column_if_missing(conn, "exams", "status", "TEXT DEFAULT 'draft'")
    _sqlite_add_column_if_missing(conn, "exams", "admin_certification_approved", "BOOLEAN DEFAULT 0")
    # SQLite cannot add columns with non-constant defaults to an existing table.
    # ORM/server defaults still apply for newly created databases.
    _sqlite_add_column_if_missing(conn, "exams", "created_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "exams", "updated_at", "DATETIME")

    _sqlite_add_column_if_missing(conn, "exam_attempts", "assigned_question_ids", "JSON")

    _sqlite_add_column_if_missing(conn, "questions", "negative_marks", "FLOAT DEFAULT 0")
    _sqlite_add_column_if_missing(conn, "questions", "difficulty_tag", "TEXT")

    _sqlite_add_column_if_missing(conn, "exam_rules", "min_questions", "INTEGER DEFAULT 25")
    _sqlite_add_column_if_missing(conn, "exam_rules", "min_pass_score", "FLOAT DEFAULT 60")
    _sqlite_add_column_if_missing(conn, "exam_rules", "max_easy_ratio", "FLOAT DEFAULT 0.70")
    _sqlite_add_column_if_missing(conn, "exam_rules", "min_syllabus_areas", "INTEGER DEFAULT 3")
    _sqlite_add_column_if_missing(conn, "exam_rules", "max_duplicate_ratio", "FLOAT DEFAULT 0.10")
    _sqlite_add_column_if_missing(conn, "exam_rules", "max_ambiguous_ratio", "FLOAT DEFAULT 0.10")
    _sqlite_add_column_if_missing(conn, "assessment_issues", "access_key", "TEXT")
    _sqlite_add_column_if_missing(conn, "assessment_issues", "access_expires_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "assessment_issues", "credential_used_at", "DATETIME")
    try:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_assessment_issues_access_key ON assessment_issues (access_key)"))
    except Exception:
        pass
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS assessment_tasks (
                id INTEGER NOT NULL PRIMARY KEY,
                assessment_id INTEGER NOT NULL UNIQUE REFERENCES exams(id),
                type VARCHAR(30) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                instructions TEXT DEFAULT '',
                marks FLOAT DEFAULT 0,
                metadata_json JSON DEFAULT '{}',
                expected_output_json JSON DEFAULT '{}',
                grading_config_json JSON DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_tasks_assessment_id ON assessment_tasks (assessment_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_tasks_type ON assessment_tasks (type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS assessment_submissions (
                id INTEGER NOT NULL PRIMARY KEY,
                assessment_id INTEGER NOT NULL REFERENCES exams(id),
                candidate_id INTEGER REFERENCES users(id),
                issue_id INTEGER REFERENCES assessment_issues(id),
                assessment_type VARCHAR(30) NOT NULL,
                submitted_data_json JSON DEFAULT '{}',
                score FLOAT,
                auto_score FLOAT,
                manual_score FLOAT,
                status VARCHAR(30) DEFAULT 'submitted',
                started_at DATETIME,
                submitted_at DATETIME,
                time_taken_seconds INTEGER,
                proctoring_events_json JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_submissions_assessment_id ON assessment_submissions (assessment_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_submissions_candidate_id ON assessment_submissions (candidate_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_submissions_issue_id ON assessment_submissions (issue_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_submissions_assessment_type ON assessment_submissions (assessment_type)"))


def _migrate_exam_schema_postgres(conn) -> None:
    statements = [
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS assessment_type VARCHAR(30) DEFAULT 'mcq'",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS instructions TEXT DEFAULT ''",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS assessment_about TEXT DEFAULT ''",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS tools_json JSON DEFAULT '[]'::json",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS topics_json JSON DEFAULT '[]'::json",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS timing_mode VARCHAR(20) DEFAULT 'assessment'",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS time_per_question_seconds INTEGER",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS questions_per_attempt INTEGER DEFAULT 0",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS negative_marking BOOLEAN DEFAULT FALSE",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS shuffle_questions BOOLEAN DEFAULT FALSE",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS shuffle_options BOOLEAN DEFAULT FALSE",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 1",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS certificate_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'draft'",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS admin_certification_approved BOOLEAN DEFAULT FALSE",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE exam_attempts ADD COLUMN IF NOT EXISTS assigned_question_ids JSON",
        "ALTER TABLE questions ADD COLUMN IF NOT EXISTS negative_marks FLOAT DEFAULT 0",
        "ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty_tag VARCHAR(20)",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS min_questions INTEGER DEFAULT 25",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS min_pass_score FLOAT DEFAULT 60",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS max_easy_ratio FLOAT DEFAULT 0.70",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS min_syllabus_areas INTEGER DEFAULT 3",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS max_duplicate_ratio FLOAT DEFAULT 0.10",
        "ALTER TABLE exam_rules ADD COLUMN IF NOT EXISTS max_ambiguous_ratio FLOAT DEFAULT 0.10",
        "ALTER TABLE assessment_issues ADD COLUMN IF NOT EXISTS access_key VARCHAR(120)",
        "ALTER TABLE assessment_issues ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ",
        "ALTER TABLE assessment_issues ADD COLUMN IF NOT EXISTS credential_used_at TIMESTAMPTZ",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_assessment_issues_access_key ON assessment_issues(access_key)",
        """
        CREATE TABLE IF NOT EXISTS assessment_tasks (
            id BIGSERIAL PRIMARY KEY,
            assessment_id BIGINT NOT NULL UNIQUE REFERENCES exams(id),
            type VARCHAR(30) NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            instructions TEXT DEFAULT '',
            marks FLOAT DEFAULT 0,
            metadata_json JSON DEFAULT '{}'::json,
            expected_output_json JSON DEFAULT '{}'::json,
            grading_config_json JSON DEFAULT '{}'::json,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_assessment_tasks_assessment_id ON assessment_tasks(assessment_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_tasks_type ON assessment_tasks(type)",
        """
        CREATE TABLE IF NOT EXISTS assessment_submissions (
            id BIGSERIAL PRIMARY KEY,
            assessment_id BIGINT NOT NULL REFERENCES exams(id),
            candidate_id BIGINT REFERENCES users(id),
            issue_id BIGINT REFERENCES assessment_issues(id),
            assessment_type VARCHAR(30) NOT NULL,
            submitted_data_json JSON DEFAULT '{}'::json,
            score FLOAT,
            auto_score FLOAT,
            manual_score FLOAT,
            status VARCHAR(30) DEFAULT 'submitted',
            started_at TIMESTAMPTZ,
            submitted_at TIMESTAMPTZ,
            time_taken_seconds INTEGER,
            proctoring_events_json JSON,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_assessment_submissions_assessment_id ON assessment_submissions(assessment_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_submissions_candidate_id ON assessment_submissions(candidate_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_submissions_issue_id ON assessment_submissions(issue_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_submissions_assessment_type ON assessment_submissions(assessment_type)",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def _migrate_admin_user_controls_sqlite(conn) -> None:
    _sqlite_add_column_if_missing(conn, "users", "phone_number", "TEXT")
    _sqlite_add_column_if_missing(conn, "users", "student_age", "INTEGER")
    _sqlite_add_column_if_missing(conn, "users", "account_state", "TEXT DEFAULT 'active'")
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS banned_identities (
                id INTEGER NOT NULL PRIMARY KEY,
                email VARCHAR(320),
                phone_number VARCHAR(32),
                id_type VARCHAR(40),
                id_number VARCHAR(120),
                country_code VARCHAR(8),
                source_user_id INTEGER REFERENCES users(id),
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        ),
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_banned_identities_email ON banned_identities (email)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_banned_identities_phone_number ON banned_identities (phone_number)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_banned_identities_id_type ON banned_identities (id_type)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_banned_identities_id_number ON banned_identities (id_number)"))


def _migrate_admin_user_controls_postgres(conn) -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS student_age INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS account_state VARCHAR(20) DEFAULT 'active'",
        "UPDATE users SET account_state = 'active' WHERE account_state IS NULL",
        """
        CREATE TABLE IF NOT EXISTS banned_identities (
            id BIGSERIAL PRIMARY KEY,
            email VARCHAR(320),
            phone_number VARCHAR(32),
            id_type VARCHAR(40),
            id_number VARCHAR(120),
            country_code VARCHAR(8),
            source_user_id BIGINT REFERENCES users(id),
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_banned_identities_email ON banned_identities(email)",
        "CREATE INDEX IF NOT EXISTS ix_banned_identities_phone_number ON banned_identities(phone_number)",
        "CREATE INDEX IF NOT EXISTS ix_banned_identities_id_type ON banned_identities(id_type)",
        "CREATE INDEX IF NOT EXISTS ix_banned_identities_id_number ON banned_identities(id_number)",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def _migrate_provider_feedback_schema_sqlite(conn) -> None:
    _sqlite_add_column_if_missing(conn, "course_comments", "provider_status", "TEXT DEFAULT 'new'")
    _sqlite_add_column_if_missing(conn, "course_comments", "provider_seen_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "course_feedback", "provider_seen_at", "DATETIME")
    _sqlite_add_column_if_missing(conn, "course_feedback", "provider_reply", "TEXT")
    _sqlite_add_column_if_missing(conn, "course_feedback", "provider_replied_at", "DATETIME")
    try:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_course_comments_provider_status ON course_comments (provider_status)"))
    except Exception:
        pass
    try:
        conn.execute(text("UPDATE course_comments SET provider_status = 'new' WHERE provider_status IS NULL OR provider_status = ''"))
    except Exception:
        pass


def _migrate_provider_feedback_schema_postgres(conn) -> None:
    statements = [
        "ALTER TABLE course_comments ADD COLUMN IF NOT EXISTS provider_status VARCHAR(20) DEFAULT 'new'",
        "ALTER TABLE course_comments ADD COLUMN IF NOT EXISTS provider_seen_at TIMESTAMPTZ",
        "ALTER TABLE course_feedback ADD COLUMN IF NOT EXISTS provider_seen_at TIMESTAMPTZ",
        "ALTER TABLE course_feedback ADD COLUMN IF NOT EXISTS provider_reply TEXT",
        "ALTER TABLE course_feedback ADD COLUMN IF NOT EXISTS provider_replied_at TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS ix_course_comments_provider_status ON course_comments(provider_status)",
        "UPDATE course_comments SET provider_status = 'new' WHERE provider_status IS NULL OR provider_status = ''",
    ]
    for stmt in statements:
        try:
            conn.execute(text(stmt))
        except Exception:
            pass


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            cols = conn.execute(text("PRAGMA table_info(lesson_topics)")).fetchall()
            col_names = {row[1] for row in cols}
            if "thumbnail_data_url" not in col_names:
                conn.execute(text("ALTER TABLE lesson_topics ADD COLUMN thumbnail_data_url TEXT"))

            _migrate_exam_schema_sqlite(conn)

            _migrate_proctor_training_feedback_nullable_attempt_id(conn)
            _migrate_live_class_schema_sqlite(conn)
            _migrate_identity_schema_sqlite(conn)
            _migrate_stream_market_schema_sqlite(conn)
            _migrate_admin_user_controls_sqlite(conn)
            _migrate_provider_feedback_schema_sqlite(conn)
    elif engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE proctor_training_feedback ALTER COLUMN attempt_id DROP NOT NULL"))
            except Exception:
                pass
            _migrate_exam_schema_postgres(conn)
            _migrate_live_class_schema_postgres(conn)
            _migrate_identity_schema_postgres(conn)
            _migrate_stream_market_schema_postgres(conn)
            _migrate_admin_user_controls_postgres(conn)
            _migrate_provider_feedback_schema_postgres(conn)

    # Backfill and normalize existing accounts to current role/approval rules, then sync Firebase claims.
    db = SessionLocal()
    try:
        default_source = db.query(ProctorDatasetSource).filter(ProctorDatasetSource.name == "oep_video_features").first()
        if not default_source:
            db.add(
                ProctorDatasetSource(
                    name="oep_video_features",
                    source_type="local_csv",
                    source_path="data/proctoring/processed/video_features_labeled.csv",
                    is_enabled=True,
                    notes="Baseline labeled dataset reference used for proctor model benchmarking.",
                    created_by_user_id=None,
                ),
            )
            db.commit()
        sync_existing_accounts(
            db,
            apply_legacy_student_approval_rollback=False,
            sync_firebase_claims=True,
        )
    finally:
        db.close()
