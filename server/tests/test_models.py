from app.models import (User, Region, Dialect, PoliceStation, Text, TextAssignment,
                        Recording, AudioFile, FileAssignment, Annotation, ImportTask,
                        ExportTask, UserImportBatch, Task, Message, MessageRecipient, QCLog)
import pytest
from sqlalchemy.exc import IntegrityError

def test_17_tables_registered(db):
    from app.core.database import Base
    assert len(Base.metadata.tables) == 17

def test_recording_unique_user_text(db):
    u = User(phone="33100400002", password_hash="x", real_name="a", region_code="331004", role="user"); db.add(u); db.commit()
    r = Region(code="331004", name="临海市", level="district", parent_code="331000"); db.add(r)
    t = Text(content="你好", dialect="临海方言", category="police", region_code="331004", dialect_code="dh1"); db.add(t); db.commit()
    rec = Recording(user_id=u.id, text_id=t.id, file_path="a.wav", file_size=1, duration=1.0,
                    region_code="331004", dialect_code="dh1", qc_status="pending")
    db.add(rec); db.commit()
    db.add(Recording(user_id=u.id, text_id=t.id, file_path="b.wav", file_size=1, duration=1.0,
                     region_code="331004", dialect_code="dh1", qc_status="pending"))
    with pytest.raises(IntegrityError):
        db.commit()
