-- EDW = 벡터만(사용자 2026-10-01: 벡터 외 메타 정보는 EDW에 넣지 않음). 본문·출처·고객·요약·그래프·키워드는 개발 서버(pgvector/로컬).
-- VECTOR 형이 없거나 차원이 1,998을 넘을 때(qwen3-vl-embedding 4,096): 차원마다 한 행(chunk_key, d, v), 내적 = 코사인(정규화 저장).
-- 비용 = 청크 수 × 차원 행 스캔 → 질의마다 EDW에서 계산하기보다 개발 서버로 한 번 가져와 캐시(--edw-client)가 빠름.
IF OBJECT_ID(N'[{S}].[chunk_vec_n]') IS NULL
CREATE TABLE [{S}].[chunk_vec_n] (
    d         SMALLINT NOT NULL,
    chunk_key VARCHAR(80) NOT NULL,
    v         REAL NOT NULL,
    CONSTRAINT PK_{S}_chunk_vec_n PRIMARY KEY (d, chunk_key)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_{S}_chunk_vec_n_key' AND object_id = OBJECT_ID(N'[{S}].[chunk_vec_n]'))
CREATE INDEX IX_{S}_chunk_vec_n_key ON [{S}].[chunk_vec_n](chunk_key, d) INCLUDE (v);
GO
CREATE OR ALTER PROCEDURE [{S}].[usp_vec_topk] @qvec NVARCHAR(MAX), @k INT = 50
AS
BEGIN
    SET NOCOUNT ON;
    SELECT TOP (@k) n.chunk_key, CAST(SUM(n.v * CAST(q.[value] AS REAL)) AS FLOAT) AS score
    FROM OPENJSON(@qvec) q
    JOIN [{S}].[chunk_vec_n] n ON n.d = CAST(q.[key] AS SMALLINT)
    GROUP BY n.chunk_key
    ORDER BY score DESC;
END
GO
CREATE OR ALTER PROCEDURE [{S}].[usp_vec_load] @rows NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT [{S}].[chunk_vec_n](d, chunk_key, v)
    SELECT CAST(e.[key] AS SMALLINT), j.[key], CAST(e.[value] AS REAL)
    FROM OPENJSON(@rows) WITH ([key] VARCHAR(80) '$.key', v NVARCHAR(MAX) '$.v' AS JSON) j
    CROSS APPLY OPENJSON(j.v) e;
END
GO
