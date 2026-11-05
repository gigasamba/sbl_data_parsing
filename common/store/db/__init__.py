"""pgvector 우리 스키마 관리: 표 정의(SQLAlchemy — models/, 정본) · 행 모양(pydantic — schemas/) ·
판 관리(Alembic — migrations/, 갈래 search·struct) · 명령(dbtool — up·stamp·current·check). 표·칸 이름과 형식은
docs/architecture/db_schema.md. 층 파일은 이 패키지를 import하지 않는다(판을 더해도 code_fp가 바뀌지 않게)."""
