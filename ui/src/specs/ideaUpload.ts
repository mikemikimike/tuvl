/** A file to upload and the folder-relative name it keeps (a dropped or picked folder keeps its structure). */
export interface Picked { file: File; name: string }

export const pickedFrom = (list: FileList | File[]): Picked[] =>
  Array.from(list).map((file) => ({ file, name: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name }))

export const INITIALS = /^[A-Za-z][A-Za-z0-9]{1,3}$/

/** Links typed one per line (or separated by spaces). `bad` holds what is not an http(s) link. */
export const parseLinks = (text: string): { links: string[]; bad: string[] } => {
  const words = text.split(/\s+/).filter(Boolean)
  return { links: words.filter((w) => /^https?:\/\/\S+$/i.test(w)), bad: words.filter((w) => !/^https?:\/\/\S+$/i.test(w)) }
}
