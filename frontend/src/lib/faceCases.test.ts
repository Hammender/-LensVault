import { describe, expect, it } from "vitest";
import { caseAnswerSummary, caseCreatePayload, casePath, faceBoxStyle } from "./faceCases";
import type { Face } from "../types/gallery";
import { pageFromHash } from "./routing";

describe("识别异常案例定位", () => {
  it("以 EXIF 校正后的宽高定位目标脸", () => {
    expect(faceBoxStyle({ bbox_left: 12, bbox_top: 8, bbox_right: 60, bbox_bottom: 40 }, 120, 80))
      .toEqual({ left: "10%", top: "10%", width: "40%", height: "40%" });
  });
  it("缺失坐标不绘制框，越界坐标限制在图内", () => {
    expect(faceBoxStyle({}, 120, 80)).toBeNull();
    expect(faceBoxStyle({ bbox_left: -1, bbox_top: 0, bbox_right: 130, bbox_bottom: 90 }, 120, 80))
      .toEqual({ left: "0%", top: "0%", width: "100%", height: "100%" });
  });
  it("案例详情链接可直接访问且保留原图库路由", () => {
    expect(pageFromHash(`#${casePath("abc")}`)).toBe("face-recognition-cases");
    expect(pageFromHash("#/gallery")).toBe("gallery");
    expect(pageFromHash("#/face-recognition-cases-other")).toBe("home");
  });
});

describe("人工结论切换", () => {
  const face = { id: 9, face_revision: "revision" } as Face;
  const draft = { personId: "3", excludedPersonId: "5", issue: "unknown" as const, notes: "清晰路人", bind: true };
  it("库外人物不携带之前选择的正确人物、排除人物或改绑请求", () => {
    expect(caseCreatePayload(1, face, { ...draft, answerType: "out_of_library" })).toEqual({
      photo_id: 1, face_id: 9, face_revision: "revision", answer_type: "out_of_library",
      correct_person_id: null, excluded_person_id: null, bind_person: false, issue_type: "wrong_person", notes: "清晰路人",
    });
  });
  it("仅排除指定人物不保存正例答案", () => {
    const payload = caseCreatePayload(1, face, { ...draft, answerType: "not_person" });
    expect(payload.correct_person_id).toBeNull();
    expect(payload.excluded_person_id).toBe(5);
    expect(payload.bind_person).toBe(false);
    expect(caseAnswerSummary({ answer_type: "not_person", correct_person_name: "", excluded_person_name: "甲" })).toBe("不是甲");
  });
  it("切回库中人物才允许提交改绑，清除排除人物", () => {
    const payload = caseCreatePayload(1, face, { ...draft, answerType: "known_person" });
    expect(payload.correct_person_id).toBe(3);
    expect(payload.excluded_person_id).toBeNull();
    expect(payload.bind_person).toBe(true);
    expect(payload.issue_type).toBe("unknown");
  });
});
