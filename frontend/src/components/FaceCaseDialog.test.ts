import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Face, GalleryPhotoDetail } from "../types/gallery";
import type { Person } from "../types/people";
import FaceCaseDialog from "./FaceCaseDialog";

function render(changes: Partial<Face> = {}) {
  const face = {
    id: 1, face_index: 1, face_revision: "a".repeat(64), bbox_left: 12, bbox_top: 8, bbox_right: 60, bbox_bottom: 40,
    matched_person_id: 9, matched_person_name: "未知人物", matched_person_is_unknown: true, binding_source: "unknown",
    predicted_person_id: 10, predicted_person_name: "候选甲", second_person_id: 11, second_person_name: "候选乙",
    needs_review: true, promoted_sample_id: null, ...changes,
  } as Face;
  const photo = { id: 2, original_url: "/original", display_width: 120, display_height: 80 } as GalleryPhotoDetail;
  const persons = [{ id: 99, display_name: "正确人物", is_unknown: false, sample_count: 1 }] as Person[];
  return renderToStaticMarkup(createElement(FaceCaseDialog, { face, photo, persons, onClose: () => {}, onSaved: () => {} }));
}

describe("记录识别异常弹窗", () => {
  it("未知脸不默认选候选人物，改绑默认不勾选，未指定正确人物不能保存", () => {
    const html = render();
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("搜索全部正式人物");
    expect(html).not.toContain("checked=");
    expect(html).toContain('<button type="button" disabled="">保存案例</button>');
    expect(html).toContain("候选甲");
    expect(html).toContain("候选乙");
    expect(html).toContain('<option value="out_of_library">确定是库外人物</option>');
    expect(html).toContain('<option value="not_person">只确定不是某人</option>');
  });
  it("已人工修正时带入当前正式人物，并注明当前状态", () => {
    const html = render({ binding_source: "manual", matched_person_id: 99, matched_person_name: "正确人物", matched_person_is_unknown: false });
    expect(html).toContain('value="正确人物"');
    expect(html).toContain('<button type="button">保存案例</button>');
    expect(html).toContain("这张脸已经人工绑定");
    expect(html).not.toContain("checked=");
  });
  it("已入样本的人脸仍可记录，但改绑选项锁定", () => {
    const html = render({ promoted_sample_id: 123 });
    expect(html).toContain('<input type="checkbox" disabled=""/>');
    expect(html).toContain("改绑需先撤销样本");
  });
});
