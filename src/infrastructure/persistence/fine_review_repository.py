"""`monthly_fine_review_batches` — Aylıq Cərimə İcmalı partiyasının yazı qatı (SEC-8).

──────────────────────────────────────────────────────────────────────────────
NİYƏ SADƏ `INSERT`, `ON CONFLICT` YOX
──────────────────────────────────────────────────────────────────────────────
`FineReviewBatch.id` (`new_fine_review_batch_id()`) `MonthlyFineReviewUseCase.
publish_batch()`-in İÇİNDƏ, HƏR çağırışda YENİDƏN yaradılır (bax
`fine_review.py:211`) — sessiya/saga token-ləri ilə EYNİ naxış (D6, SEC-5):
eyni ID-nin İKİNCİ dəfə `save()`-ə gəlməsi qanuni retry ssenarisi DEYİL,
anomaliyadır. Sətir bir dəfə yazılır və heç vaxt DƏYİŞMİR (sadə audit
sətridir — bax `FineReviewBatch` docstring-i, `fine_review.py`), ona görə
UPDATE budağı da lazım deyil.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.application.use_cases.fine_review import FineReviewBatch


class PostgresFineReviewBatchRepository(_BaseRepository):
    """`FineReviewBatchRepository` Protocol-una STRUCTURAL uyğun (miras YOX)."""

    def save(self, batch: FineReviewBatch) -> None:
        self._execute(
            """
            INSERT INTO monthly_fine_review_batches
                (id, tenant_id, reviewed_by, review_month, pushed_at,
                 total_kept_count, total_reversed_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                batch.id,
                # `self._tenant` DEYİL, `batch.tenant_id` — bu, YENİ sətrin
                # AÇARIDIR (INSERT dəyəri), `WHERE` şərti deyil. RLS
                # `WITH CHECK (tenant_id = current_tenant_id())` bu dəyərin
                # bağlantının ÖZ kirayəçisi ilə uyğun olmasını MƏCBUR EDİR —
                # `auth_session_repository.py::save()`-dəki EYNİ qərar.
                batch.tenant_id,
                batch.reviewed_by,
                batch.review_month,
                batch.pushed_at,
                batch.total_kept_count,
                batch.total_reversed_count,
            ),
        )


__all__ = ["PostgresFineReviewBatchRepository"]
