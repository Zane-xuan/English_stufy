"""落库。当天内容与词汇一次事务写完。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.db import (
    connection,
    delete_daily_content,
    has_content,
    insert_daily_content,
    insert_vocabulary,
    log_fetch,
)
from app.errors import StoreError
from app.models import (
    RESULT_SUCCESS,
    STAGE_STORE,
    DailyContent,
    FetchLogEntry,
    VocabularyItem,
)

logger = logging.getLogger(__name__)


def save_content(
    content: DailyContent,
    vocabulary: Sequence[VocabularyItem],
    *,
    replace: bool = False,
) -> int:
    """写入当天内容与词汇，返回内容 id。

    replace 为真时先删掉当天旧记录与旧词汇，避免重复累积。
    """
    with connection() as conn:
        if replace:
            delete_daily_content(conn, content.content_date)
        elif has_content(conn, content.content_date):
            raise StoreError(f"{content.content_date} 已有记录，未指定覆盖")

        content_id = insert_daily_content(conn, content)
        insert_vocabulary(conn, content_id, vocabulary)
        log_fetch(
            conn,
            FetchLogEntry(
                run_date=content.content_date,
                stage=STAGE_STORE,
                result=RESULT_SUCCESS,
                message=f"写入 1 条内容与 {len(vocabulary)} 条词汇",
            ),
        )

    logger.info("已写入 %s，词汇 %s 条", content.content_date, len(vocabulary))
    return content_id
