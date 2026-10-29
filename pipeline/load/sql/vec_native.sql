-- EDW = 벡터만(사용자 2026-10-01: 벡터 외 메타 정보는 EDW에 넣지 않음). 본문·출처·고객·요약·그래프·키워드는 개발 서버(pgvector/로컬).
-- SQL Server 2025+ VECTOR 형(차원 ≤1,998). chunk_key = '<원본 파일 sha256>:<청크 순번>' — 개발 서버 묶음의 같은 청크를 가리키는 키.
IF OBJECT_ID(N'[{S}].[chunk_vec]') IS NULL
CREATE TABLE [{S}].[chunk_vec] (
    chunk_key VARCHAR(80) NOT NULL PRIMARY KEY,
    emb       VECTOR({DIM}) NOT NULL
);
GO
-- 질의 벡터(JSON 배열 문자열) → 코사인 거리 가까운 순 상위 @k (정확 검색)
CREATE OR ALTER PROCEDURE [{S}].[usp_vec_topk] @qvec NVARCHAR(MAX), @k INT = 50
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @q VECTOR({DIM}) = CAST(@qvec AS VECTOR({DIM}));
    SELECT TOP (@k) v.chunk_key, CAST(1.0 - VECTOR_DISTANCE('cosine', v.emb, @q) AS FLOAT) AS score
    FROM [{S}].[chunk_vec] v
    ORDER BY VECTOR_DISTANCE('cosine', v.emb, @q);
END
GO
-- 적재: JSON [{"key":"<sha>:<seq>","v":[...]}, …]
CREATE OR ALTER PROCEDURE [{S}].[usp_vec_load] @rows NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT [{S}].[chunk_vec](chunk_key, emb)
    SELECT j.[key], CAST(j.v AS VECTOR({DIM}))
    FROM OPENJSON(@rows) WITH ([key] VARCHAR(80) '$.key', v NVARCHAR(MAX) '$.v' AS JSON) j;
END
GO
