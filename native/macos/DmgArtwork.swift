import AppKit
let size=NSSize(width:960,height:620)
let image=NSImage(size:size)
image.lockFocus()
NSGradient(starting:NSColor(calibratedRed:0.97,green:0.98,blue:1,alpha:1),ending:NSColor(calibratedRed:0.88,green:0.93,blue:0.99,alpha:1))!.draw(in:NSRect(origin:.zero,size:size),angle:90)
func text(_ string:String,_ y:CGFloat,_ font:NSFont,_ color:NSColor){let attrs:[NSAttributedString.Key:Any]=[.font:font,.foregroundColor:color];let width=(string as NSString).size(withAttributes:attrs).width;(string as NSString).draw(at:NSPoint(x:(size.width-width)/2,y:y),withAttributes:attrs)}
text("Dagami",480,.systemFont(ofSize:46,weight:.bold),NSColor(calibratedRed:0.08,green:0.12,blue:0.19,alpha:1))
text("Ваши приложения. Ваш маршрут.",440,.systemFont(ofSize:19,weight:.regular),NSColor(calibratedRed:0.36,green:0.41,blue:0.48,alpha:1))
NSColor.white.withAlphaComponent(0.7).setFill();NSBezierPath(roundedRect:NSRect(x:100,y:150,width:760,height:235),xRadius:30,yRadius:30).fill()
let arrow=NSImage(systemSymbolName:"arrow.right",accessibilityDescription:nil)!
arrow.draw(in:NSRect(x:455,y:245,width:50,height:42))
text("Перетащите Dagami в Программы",95,.systemFont(ofSize:20,weight:.medium),NSColor(calibratedRed:0.08,green:0.12,blue:0.19,alpha:1))
text("macOS 13+  ·  Intel и Apple silicon",57,.systemFont(ofSize:13,weight:.regular),NSColor(calibratedRed:0.36,green:0.41,blue:0.48,alpha:1))
image.unlockFocus()
let data=NSBitmapImageRep(data:image.tiffRepresentation!)!.representation(using:.png,properties:[:])!
try data.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
