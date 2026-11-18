import AVFoundation
import CoreImage
import Vision
import AppKit

// grade <in> <out.png|out.mp4> <start> <dur> <key> [options]
//
// Makes footage black and white but keeps ONE object in a brand colour, with a clean hard-edged mask.
//
// key (what identifies the object, per pixel):
//   gray                                   no colour at all
//   luma:<t>:<colour>[:gamma[:gain]]       brighter than t (0-1)
//   white:<t>:<smax>:<colour>[:gamma[:gain]]  brighter than t AND saturation below smax (cloth, snow; not skin or sky)
//   hue:<h0>:<h1>:<smin>:<colour>[:gamma[:gain]]  hue between h0 and h1 degrees, saturation above smin
// options (clean the mask up so the colour sits exactly on the object):
//   region:x0,y0,x1,y1   only inside this box (fractions, origin top-left); repeat for several boxes
//   fg                   only on the foreground subject Apple Vision finds in each frame
//   close:N              fill gaps and holes up to N pixels (at 4K) so the object is covered evenly
//   open:N               drop stray specks smaller than N pixels
//   bw:r,g,b             weights for the black-and-white conversion (default 0.21,0.72,0.07)
// Output is 3840x2160.

let a = CommandLine.arguments
let inURL = URL(fileURLWithPath: a[1]), outURL = URL(fileURLWithPath: a[2])
let start = Double(a[3])!, dur = Double(a[4])!
let key = a[5].split(separator: ":").map(String.init)
var regions: [[CGFloat]] = []
var useFG = false
var closeR: Double = 0, openR: Double = 0
var bw: [Float] = [0.2126, 0.7152, 0.0722]
var bottomBand: CGFloat = 0 // fg only: keep just this fraction of the frame height above the subject's lowest point (a shoe, not the leg)
for extra in a.dropFirst(6) {
  if extra.hasPrefix("region:") { regions.append(extra.dropFirst(7).split(separator: ",").map { CGFloat(Double($0)!) }) }
  if extra == "fg" { useFG = true }
  if extra.hasPrefix("close:") { closeR = Double(extra.dropFirst(6))! }
  if extra.hasPrefix("open:") { openR = Double(extra.dropFirst(5))! }
  if extra.hasPrefix("bottom:") { bottomBand = CGFloat(Double(extra.dropFirst(7))!) }
  if extra.hasPrefix("bw:") { bw = extra.dropFirst(3).split(separator: ",").map { Float($0)! } }
}
let W: CGFloat = 3840, H: CGFloat = 2160
let BLUE: [Float] = [120.0 / 255, 175.0 / 255, 1.0], GREEN: [Float] = [188.0 / 255, 235.0 / 255, 156.0 / 255]
func brand(_ name: String) -> [Float] { let c = name == "green" ? GREEN : BLUE; let m = c.max()!; return c.map { $0 / m } }
func step(_ edge: Float, _ x: Float) -> Float { max(0, min(1, (x - edge) / 0.03 + 0.5)) } // a narrow ramp, nearly a hard edge

// Field positions differ per key; find the colour name and the optional gamma and gain after it.
let ci = key.firstIndex(where: { $0 == "blue" || $0 == "green" }) ?? -1
let tint: [Float] = ci >= 0 ? brand(key[ci]) : [1, 1, 1]
let gamma: Float = ci >= 0 && key.count > ci + 1 ? Float(key[ci + 1])! : 0.8
let gain: Float = ci >= 0 && key.count > ci + 2 ? Float(key[ci + 2])! : 1

let N = 48
var greyCube = [Float](repeating: 0, count: N * N * N * 4)   // the black-and-white look
var keyCube = [Float](repeating: 0, count: N * N * N * 4)    // white where the pixel matches the key
var tintCube = [Float](repeating: 0, count: N * N * N * 4)   // the whole frame in the brand colour
for bi in 0..<N { for gi in 0..<N { for ri in 0..<N {
  let r = Float(ri) / Float(N - 1), g = Float(gi) / Float(N - 1), b = Float(bi) / Float(N - 1)
  let luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
  let grey = max(0, min(1, bw[0] * r + bw[1] * g + bw[2] * b))
  let mx = max(r, g, b), mn = min(r, g, b), d = mx - mn
  let sat = mx <= 1e-5 ? 0 : d / mx
  var m: Float = 0
  if key[0] == "luma" { m = step(Float(key[1])!, luma) }
  else if key[0] == "white" { m = step(Float(key[1])!, luma) * (1 - step(Float(key[2])!, sat)) }
  else if key[0] == "hue" {
    var h: Float = 0
    if d > 1e-5 { if mx == r { h = (g - b) / d } else if mx == g { h = 2 + (b - r) / d } else { h = 4 + (r - g) / d }; h *= 60; if h < 0 { h += 360 } }
    let inHue: Float = (h >= Float(key[1])! && h <= Float(key[2])!) ? 1 : 0
    m = inHue * step(Float(key[3])!, sat) * step(0.1, mx)
  }
  let level = min(1, pow(max(grey, 0.0001), gamma) * gain)
  let i = (bi * N * N + gi * N + ri) * 4
  greyCube[i] = grey; greyCube[i + 1] = grey; greyCube[i + 2] = grey; greyCube[i + 3] = 1
  keyCube[i] = m; keyCube[i + 1] = m; keyCube[i + 2] = m; keyCube[i + 3] = 1
  tintCube[i] = tint[0] * level; tintCube[i + 1] = tint[1] * level; tintCube[i + 2] = tint[2] * level; tintCube[i + 3] = 1
}}}
func data(_ c: [Float]) -> Data { c.withUnsafeBufferPointer { Data(buffer: $0) } }
let greyData = data(greyCube), keyData = data(keyCube), tintData = data(tintCube)
let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CIContext(options: [.workingColorSpace: srgb])
let frame = CGRect(x: 0, y: 0, width: W, height: H)
func cube(_ image: CIImage, _ d: Data) -> CIImage {
  image.applyingFilter("CIColorCubeWithColorSpace", parameters: ["inputCubeDimension": N, "inputCubeData": d, "inputColorSpace": srgb])
}
func morph(_ image: CIImage, _ name: String, _ r: Double) -> CIImage {
  r <= 0 ? image : image.clampedToExtent().applyingFilter(name, parameters: [kCIInputRadiusKey: r]).cropped(to: frame)
}
func both(_ x: CIImage, _ y: CIImage) -> CIImage { x.applyingFilter("CIMultiplyCompositing", parameters: [kCIInputBackgroundImageKey: y]) }

func look(_ src0: CIImage) -> CIImage {
  let s = max(W / src0.extent.width, H / src0.extent.height)
  var src = src0.transformed(by: CGAffineTransform(scaleX: s, y: s))
  src = src.transformed(by: CGAffineTransform(translationX: (W - src.extent.width) / 2 - src.extent.minX, y: (H - src.extent.height) / 2 - src.extent.minY)).cropped(to: frame)
  let grey = cube(src, greyData)
  if key[0] == "gray" { return grey }

  // 1. Which pixels look like the object. A light blur first so film grain does not speckle the key.
  var mask = cube(src.clampedToExtent().applyingGaussianBlur(sigma: 2).cropped(to: frame), keyData)
  // 2. Keep it to where the object can be.
  for (i, rg) in regions.enumerated() where i == 0 {
    var boxes = CIImage(color: .black).cropped(to: frame)
    for r in regions {
      let rect = CGRect(x: r[0] * W, y: (1 - r[3]) * H, width: (r[2] - r[0]) * W, height: (r[3] - r[1]) * H)
      boxes = CIImage(color: .white).cropped(to: rect).composited(over: boxes)
    }
    _ = rg
    mask = both(mask, boxes)
  }
  var subject: CIImage? = nil
  var band: CIImage? = nil
  if useFG {
    let k = 1280 / W
    let small = src.transformed(by: CGAffineTransform(scaleX: k, y: k))
    subject = CIImage(color: .black).cropped(to: frame)
    if let cg = ctx.createCGImage(small, from: small.extent) {
      let req = VNGenerateForegroundInstanceMaskRequest()
      let handler = VNImageRequestHandler(cgImage: cg)
      if (try? handler.perform([req])) != nil, let obs = req.results?.first,
         let buf = try? obs.generateScaledMaskForImage(forInstances: obs.allInstances, from: handler) {
        let fg = CIImage(cvPixelBuffer: buf)
        if bottomBand > 0 {
          // Find the lowest row of the subject, then keep only a band above it.
          CVPixelBufferLockBaseAddress(buf, .readOnly)
          let bw_ = CVPixelBufferGetWidth(buf), bh = CVPixelBufferGetHeight(buf), rowBytes = CVPixelBufferGetBytesPerRow(buf)
          let fmt = CVPixelBufferGetPixelFormatType(buf)
          var lowest = -1
          if let base = CVPixelBufferGetBaseAddress(buf) {
            rows: for y in stride(from: bh - 1, through: 0, by: -1) {
              var count = 0
              for x in stride(from: 0, to: bw_, by: 2) {
                let on: Bool
                if fmt == kCVPixelFormatType_OneComponent32Float { on = base.advanced(by: y * rowBytes + x * 4).assumingMemoryBound(to: Float.self).pointee > 0.5 }
                else { on = base.advanced(by: y * rowBytes + x).assumingMemoryBound(to: UInt8.self).pointee > 127 }
                if on { count += 1; if count > 12 { lowest = y; break rows } }
              }
            }
          }
          CVPixelBufferUnlockBaseAddress(buf, .readOnly)
          if lowest >= 0 {
            let low = CGFloat(lowest + 1) / CGFloat(bh)            // fraction from the top
            let top = max(0, low - bottomBand)
            let rect = CGRect(x: 0, y: (1 - low) * H, width: W, height: (low - top) * H) // CI's origin is bottom-left
            band = CIImage(color: .white).cropped(to: rect).composited(over: CIImage(color: .black).cropped(to: frame))
          }
        }
        // Pull the subject's edge in a few pixels so the colour never spills onto the background.
        subject = morph(fg.transformed(by: CGAffineTransform(scaleX: W / fg.extent.width, y: H / fg.extent.height)).cropped(to: frame), "CIMorphologyMinimum", 5)
      }
    }
    mask = both(mask, subject!)
    if let b = band { mask = both(mask, b) }
  }
  // 3. Fill gaps so the object is covered evenly, then drop specks.
  mask = morph(morph(mask, "CIMorphologyMaximum", closeR), "CIMorphologyMinimum", closeR)
  mask = morph(morph(mask, "CIMorphologyMinimum", openR), "CIMorphologyMaximum", openR)
  if let subj = subject { mask = both(mask, subj) } // filling must not leak past the subject's outline
  if let b = band { mask = both(mask, b) }
  // 4. A hard edge, softened by about a pixel so it is not jagged.
  mask = mask.applyingFilter("CIColorThreshold", parameters: ["inputThreshold": 0.5])
    .clampedToExtent().applyingGaussianBlur(sigma: 1.6).cropped(to: frame)
  return cube(src, tintData).applyingFilter("CIBlendWithMask", parameters: [kCIInputBackgroundImageKey: grey, kCIInputMaskImageKey: mask])
}

let asset = AVURLAsset(url: inURL)
let comp = AVMutableVideoComposition(asset: asset) { request in
  request.finish(with: look(request.sourceImage), context: ctx)
}
comp.renderSize = CGSize(width: W, height: H)
let range = CMTimeRange(start: CMTime(seconds: start, preferredTimescale: 600), duration: CMTime(seconds: dur, preferredTimescale: 600))
try? FileManager.default.removeItem(at: outURL)
if outURL.pathExtension == "png" {
  let gen = AVAssetImageGenerator(asset: asset)
  gen.videoComposition = comp; gen.appliesPreferredTrackTransform = true
  gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
  gen.maximumSize = CGSize(width: W, height: H)
  let cg = try! gen.copyCGImage(at: range.start, actualTime: nil)
  try! NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])!.write(to: outURL)
  print("ok png \(cg.width)x\(cg.height)")
} else {
  let sem = DispatchSemaphore(value: 0)
  let ex = AVAssetExportSession(asset: asset, presetName: AVAssetExportPreset3840x2160)!
  ex.videoComposition = comp; ex.timeRange = range; ex.outputURL = outURL; ex.outputFileType = .mp4
  ex.exportAsynchronously { sem.signal() }
  sem.wait()
  print(ex.status == .completed ? "ok video" : "failed")
}
