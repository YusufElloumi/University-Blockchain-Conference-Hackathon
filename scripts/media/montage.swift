import AVFoundation
let args = CommandLine.arguments
// usage: montage out.mp4 preset file:start:dur ...
let out = URL(fileURLWithPath: args[1]); let preset = args[2]
let comp = AVMutableComposition()
let track = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
var cursor = CMTime.zero
for spec in args[3...] {
  let p = spec.split(separator: ":")
  let asset = AVURLAsset(url: URL(fileURLWithPath: String(p[0])))
  let src = asset.tracks(withMediaType: .video)[0]
  let range = CMTimeRange(start: CMTime(seconds: Double(p[1])!, preferredTimescale: 600), duration: CMTime(seconds: Double(p[2])!, preferredTimescale: 600))
  try! track.insertTimeRange(range, of: src, at: cursor)
  cursor = cursor + range.duration
}
try? FileManager.default.removeItem(at: out)
let ex = AVAssetExportSession(asset: comp, presetName: preset)!
ex.outputURL = out; ex.outputFileType = .mp4; ex.shouldOptimizeForNetworkUse = true
let sem = DispatchSemaphore(value: 0)
ex.exportAsynchronously { sem.signal() }
sem.wait()
print(ex.status == .completed ? "ok" : "failed: \(String(describing: ex.error))")
