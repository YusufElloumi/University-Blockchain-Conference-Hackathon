import AVFoundation
import CoreImage
import Vision
import AppKit

// usage: grade <in> <out.png|out.mp4> <start> <dur> <mode> [region:x0,y0,x1,y1] [fg]
//   mode: gray
//         luma:<t0>:<t1>:<blue|green>          tint pixels brighter than t0..t1 (0-1)
//         hue:<h0>:<h1>:<smin>:<blue|green>    tint pixels whose hue (degrees) is in h0..h1 and saturation > smin
//   region  limits the tint to a soft-edged box (fractions of width/height, origin top-left)
//   fg      limits the tint to the foreground subject found by Vision
// Everything else becomes black and white. Output is always 3840x2160.

let a = CommandLine.arguments
let inURL = URL(fileURLWithPath: a[1]), outURL = URL(fileURLWithPath: a[2])
let start = Double(a[3])!, dur = Double(a[4])!
let mode = a[5].split(separator: ":").map(String.init)
var regions: [[CGFloat]] = []
var useFG = false
for extra in a.dropFirst(6) {
  if extra.hasPrefix("region:") { regions.append(extra.dropFirst(7).split(separator: ",").map { CGFloat(Double($0)!) }) }
  if extra == "fg" { useFG = true }
}
let W: CGFloat = 3840, H: CGFloat = 2160
let BLUE: [Float] = [120.0 / 255, 175.0 / 255, 1.0], GREEN: [Float] = [188.0 / 255, 235.0 / 255, 156.0 / 255]
func brand(_ name: String) -> [Float] { let c = name == "green" ? GREEN : BLUE; let m = c.max()!; return c.map { $0 / m } }
func smooth(_ e0: Float, _ e1: Float, _ x: Float) -> Float { let t = max(0, min(1, (x - e0) / max(1e-5, e1 - e0))); return t * t * (3 - 2 * t) }

// Build a colour lookup cube (in sRGB) that does the whole look: grey everywhere, brand colour where the key matches.
let N = 48
var cube = [Float](repeating: 0, count: N * N * N * 4)
for bi in 0..<N { for gi in 0..<N { for ri in 0..<N {
  let r = Float(ri) / Float(N - 1), g = Float(gi) / Float(N - 1), b = Float(bi) / Float(N - 1)
  let luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
  var out: [Float] = [luma, luma, luma]
  var m: Float = 0
  var tint: [Float] = [1, 1, 1]
  var level = luma
  if mode[0] == "luma" {
    m = smooth(Float(mode[1])!, Float(mode[2])!, luma); tint = brand(mode[3]); level = min(1, pow(luma, mode.count > 4 ? Float(mode[4])! : 0.8) * (mode.count > 5 ? Float(mode[5])! : 1))
  } else if mode[0] == "white" {
    // white:<t0>:<t1>:<smax>:<colour>[:gamma[:gain]]  bright AND nearly colourless (cloth, not skin)
    let mx = max(r, g, b), mn = min(r, g, b)
    let s = mx <= 1e-5 ? 0 : (mx - mn) / mx
    let smax = Float(mode[3])!
    m = smooth(Float(mode[1])!, Float(mode[2])!, luma) * (1 - smooth(smax, smax + 0.08, s)); tint = brand(mode[4])
    level = min(1, pow(luma, mode.count > 5 ? Float(mode[5])! : 0.8) * (mode.count > 6 ? Float(mode[6])! : 1))
  } else if mode[0] == "hue" {
    let mx = max(r, g, b), mn = min(r, g, b), d = mx - mn
    var h: Float = 0
    if d > 1e-5 { if mx == r { h = (g - b) / d } else if mx == g { h = 2 + (b - r) / d } else { h = 4 + (r - g) / d }; h *= 60; if h < 0 { h += 360 } }
    let s = mx <= 1e-5 ? 0 : d / mx
    let h0 = Float(mode[1])!, h1 = Float(mode[2])!, smin = Float(mode[3])!
    let inHue = smooth(h0 - 8, h0, h) * (1 - smooth(h1, h1 + 8, h))
    m = inHue * smooth(smin, smin + 0.12, s) * smooth(0.08, 0.2, mx); tint = brand(mode[4]); level = mx
  }
  if m > 0 { for k in 0..<3 { out[k] = out[k] * (1 - m) + tint[k] * level * m } }
  let i = (bi * N * N + gi * N + ri) * 4
  cube[i] = out[0]; cube[i + 1] = out[1]; cube[i + 2] = out[2]; cube[i + 3] = 1
}}}
let cubeData = cube.withUnsafeBufferPointer { Data(buffer: $0) }
let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CIContext(options: [.workingColorSpace: srgb])

func look(_ src0: CIImage) -> CIImage {
  // Scale the frame to fill 4K.
  let s = max(W / src0.extent.width, H / src0.extent.height)
  var src = src0.transformed(by: CGAffineTransform(scaleX: s, y: s))
  src = src.transformed(by: CGAffineTransform(translationX: (W - src.extent.width) / 2 - src.extent.minX, y: (H - src.extent.height) / 2 - src.extent.minY))
  let frame = CGRect(x: 0, y: 0, width: W, height: H)
  src = src.cropped(to: frame)
  let grey = src.applyingFilter("CIColorControls", parameters: [kCIInputSaturationKey: 0])
  if mode[0] == "gray" { return grey }
  let graded = src.applyingFilter("CIColorCubeWithColorSpace", parameters: ["inputCubeDimension": N, "inputCubeData": cubeData, "inputColorSpace": srgb])
  var mask: CIImage? = nil
  for rg in regions { // several boxes add together
    let rect = CGRect(x: rg[0] * W, y: (1 - rg[3]) * H, width: (rg[2] - rg[0]) * W, height: (rg[3] - rg[1]) * H)
    let box = CIImage(color: .white).cropped(to: rect).composited(over: CIImage(color: .black).cropped(to: frame))
      .clampedToExtent().applyingGaussianBlur(sigma: 36).cropped(to: frame)
    mask = mask == nil ? box : box.applyingFilter("CIMaximumCompositing", parameters: [kCIInputBackgroundImageKey: mask!])
  }
  if useFG {
    let k = 1024 / W
    let small = src.transformed(by: CGAffineTransform(scaleX: k, y: k))
    if let cg = ctx.createCGImage(small, from: small.extent) {
      let req = VNGenerateForegroundInstanceMaskRequest()
      let handler = VNImageRequestHandler(cgImage: cg)
      if (try? handler.perform([req])) != nil, let obs = req.results?.first,
         let buf = try? obs.generateScaledMaskForImage(forInstances: obs.allInstances, from: handler) {
        var fg = CIImage(cvPixelBuffer: buf)
        fg = fg.transformed(by: CGAffineTransform(scaleX: W / fg.extent.width, y: H / fg.extent.height))
          .clampedToExtent().applyingGaussianBlur(sigma: 6).cropped(to: frame)
        mask = mask == nil ? fg : fg.applyingFilter("CIMultiplyCompositing", parameters: [kCIInputBackgroundImageKey: mask!])
      } else {
        mask = CIImage(color: .black).cropped(to: frame) // no subject found: leave this frame grey
      }
    }
  }
  guard let m = mask else { return graded }
  return graded.applyingFilter("CIBlendWithMask", parameters: [kCIInputBackgroundImageKey: grey, kCIInputMaskImageKey: m])
}

let asset = AVURLAsset(url: inURL)
let comp = AVMutableVideoComposition(asset: asset) { request in
  request.finish(with: look(request.sourceImage), context: ctx)
}
comp.renderSize = CGSize(width: W, height: H)
let range = CMTimeRange(start: CMTime(seconds: start, preferredTimescale: 600), duration: CMTime(seconds: dur, preferredTimescale: 600))
try? FileManager.default.removeItem(at: outURL)
let sem = DispatchSemaphore(value: 0)
if outURL.pathExtension == "png" {
  let gen = AVAssetImageGenerator(asset: asset)
  gen.videoComposition = comp; gen.appliesPreferredTrackTransform = true
  gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
  gen.maximumSize = CGSize(width: W, height: H)
  let cg = try! gen.copyCGImage(at: range.start, actualTime: nil)
  let rep = NSBitmapImageRep(cgImage: cg)
  try! rep.representation(using: .png, properties: [:])!.write(to: outURL)
  print("ok png \(cg.width)x\(cg.height)")
} else {
  let ex = AVAssetExportSession(asset: asset, presetName: AVAssetExportPreset3840x2160)!
  ex.videoComposition = comp; ex.timeRange = range; ex.outputURL = outURL; ex.outputFileType = .mp4
  ex.exportAsynchronously { sem.signal() }
  sem.wait()
  print(ex.status == .completed ? "ok video" : "failed: \(String(describing: ex.error))")
}
