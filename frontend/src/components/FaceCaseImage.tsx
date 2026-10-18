import { faceBoxStyle } from "../lib/faceCases";

type Props = {
  url: string;
  width: number;
  height: number;
  face: { bbox_left?: number; bbox_top?: number; bbox_right?: number; bbox_bottom?: number };
};
export default function FaceCaseImage({ url, width, height, face }: Props) {
  const box = faceBoxStyle(face, width, height);
  return <div className="face-case-image" style={width > 0 && height > 0 ? { aspectRatio: `${width} / ${height}` } : undefined}>
    <img src={url} alt="案例原图，框线标出目标人脸" />
    {box && <span className="face-case-box" style={box} aria-label="目标人脸" />}
  </div>;
}
