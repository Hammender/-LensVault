from types import SimpleNamespace

from sqlalchemy import insert

from app.api.acquisition import list_import_batches
from app.models import (
    AcquisitionAsset,
    AcquisitionCategory,
    AcquisitionImportBatch,
    AcquisitionImportBatchItem,
    AcquisitionImportedPhoto,
    AcquisitionRun,
    AcquisitionSource,
    Workspace,
)


def test_import_history_statistics_stay_within_linear_query_budget(db_session):
    """用指令预算防止逐图片扫描成功条目的退化，不依赖机器运行速度。"""
    db = db_session
    workspace = Workspace(name="测试工作区")
    other_workspace = Workspace(name="其他工作区")
    db.add_all([workspace, other_workspace])
    db.flush()
    source = AcquisitionSource(workspace_id=workspace.id, name="测试来源", base_url="https://example.test")
    db.add(source)
    db.flush()
    category = AcquisitionCategory(source_id=source.id, name="测试分类", path="test", crawl_url="https://example.test/test")
    db.add(category)
    db.flush()
    run = AcquisitionRun(id="history-run", workspace_id=workspace.id, source_id=source.id, category_id=category.id)
    batch = AcquisitionImportBatch(id="history-batch", workspace_id=workspace.id, status="completed")
    other_batch = AcquisitionImportBatch(id="other-batch", workspace_id=other_workspace.id, status="completed")
    db.add_all([run, batch, other_batch])
    db.flush()

    count = 1500
    db.execute(insert(AcquisitionAsset), [
        {"id": f"asset-{index}", "workspace_id": workspace.id, "sha256": f"{index:064x}",
         "filename": f"{index}.jpg", "status": "imported"}
        for index in range(count + 3)
    ])
    db.execute(insert(AcquisitionImportedPhoto), [
        {"run_id": run.id, "asset_id": f"asset-{index}", "gallery_photo_snapshot_id": index,
         "filename_snapshot": f"{index}.jpg", "sha256_snapshot": f"{index:064x}", "category_path_snapshot": "test"}
        for index in range(count + 3)
    ])
    db.execute(insert(AcquisitionImportBatchItem), [
        {"batch_id": batch.id, "asset_id": f"asset-{index}", "ordinal": index, "status": "imported"}
        for index in range(count)
    ] + [
        {"batch_id": batch.id, "asset_id": f"asset-{count}", "ordinal": count, "status": "failed"},
        {"batch_id": other_batch.id, "asset_id": f"asset-{count + 1}", "ordinal": 0, "status": "imported"},
    ])
    db.commit()

    connection = db.connection().connection.driver_connection
    instructions = 0

    def budget_exceeded():
        nonlocal instructions
        instructions += 1000
        return int(instructions > 500_000)

    connection.set_progress_handler(budget_exceeded, 1000)
    try:
        result = list_import_batches(
            offset=0, limit=15, date_from=None, date_to=None,
            db=db, current=SimpleNamespace(workspace_id=workspace.id),
        )
    finally:
        connection.set_progress_handler(None, 0)

    assert result.total == 1
    # 失败条目、仅其他工作区成功的条目、无批次条目均保留为历史素材。
    assert result.unassigned_imported_count == 3
