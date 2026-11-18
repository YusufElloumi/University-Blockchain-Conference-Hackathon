import AVFoundation
// usage: encode in.mp4 out.mp4 width height bitsPerSecond
let a = CommandLine.arguments
let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
let out = URL(fileURLWithPath: a[2]); try? FileManager.default.removeItem(at: out)
let w = Int(a[3])!, h = Int(a[4])!, rate = Int(a[5])!
let track = asset.tracks(withMediaType: .video)[0]
let reader = try! AVAssetReader(asset: asset)
let rout = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
reader.add(rout)
let writer = try! AVAssetWriter(outputURL: out, fileType: .mp4)
writer.shouldOptimizeForNetworkUse = true
let win = AVAssetWriterInput(mediaType: .video, outputSettings: [
  AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: w, AVVideoHeightKey: h,
  AVVideoScalingModeKey: AVVideoScalingModeResizeAspectFill,
  AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: rate, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel, AVVideoMaxKeyFrameIntervalKey: 60],
])
win.expectsMediaDataInRealTime = false
writer.add(win)
reader.startReading(); writer.startWriting(); writer.startSession(atSourceTime: .zero)
let sem = DispatchSemaphore(value: 0)
win.requestMediaDataWhenReady(on: DispatchQueue(label: "enc")) {
  while win.isReadyForMoreMediaData {
    if let s = rout.copyNextSampleBuffer() { win.append(s) } else { win.markAsFinished(); writer.finishWriting { sem.signal() }; return }
  }
}
sem.wait()
print(writer.status == .completed ? "ok" : "failed \(String(describing: writer.error))")
