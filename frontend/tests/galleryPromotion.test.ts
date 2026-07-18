import { afterEach, describe, expect, it, vi } from "vitest";

import { addGalleryPhotoPerson, promoteGalleryPhotoPersonSample, undoGalleryPhotoPersonSample } from "../src/api";

describe("gallery face promotion request", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps person tagging separate from sample promotion", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 1 }) });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });

    await addGalleryPhotoPerson(8, 12);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ person_id: 12 });
  });

  it("offers a separate promotion request for an existing person tag", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });

    await promoteGalleryPhotoPersonSample(8, 12);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/gallery/photos/8/persons/12/sample",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("offers a symmetric undo request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("window", { fetch: fetchMock, localStorage: { getItem: () => null } });

    await undoGalleryPhotoPersonSample(8, 12);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/gallery/photos/8/persons/12/sample",
      expect.objectContaining({ method: "DELETE" })
    );
  });
});
