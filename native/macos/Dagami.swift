import SwiftUI
import AppKit

struct Profile: Decodable, Identifiable {
    var id:String; var name:String; var dns:Bool; var proxy:Bool; var endpoints:[String]; var scope:String; var domains:[String]
    var subtitle:String { dns ? (proxy ? "Smart DNS + прокси" : "Smart DNS · без прокси") : (proxy ? "Прокси" : "Обычная сеть") }
}
struct ClientApp: Decodable, Identifiable { var id:String;var name:String;var path:String;var installed:Bool;var prepared:Bool;var launchError:String? }
struct NetworkService:Decodable,Identifiable { var id:String;var name:String }
struct Snapshot:Decodable {
    var profiles:[Profile]=[];var apps:[ClientApp]=[];var services:[NetworkService]=[]
    var systemDNS:String="Нет данных";var activated:Bool=false;var startup:Bool=false;var providers:[String:[String]]=[:]
}
struct AuthState:Decodable {
    var service:String?=nil;var profile:String?=nil
    var message:String="Сессия входа не запущена";var url:String="";var code:String="";var running:Bool=false
}
final class RPC: @unchecked Sendable {
    private let queue=DispatchQueue(label:"ru.dagami.bridge")
    private var process:Process?; private var input:FileHandle?;private var output:FileHandle?;private var buffer=Data()
    func call(_ action:String,_ args:[String:Any]=[:]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if self.process == nil { try self.start() }
                    let data=try JSONSerialization.data(withJSONObject:["action":action,"args":args])
                    try self.input!.write(contentsOf:data+Data([10]))
                    while !self.buffer.contains(10) {
                        let chunk=self.output!.availableData
                        if chunk.isEmpty { throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:"Служба приложения завершилась. Перезапустите Dagami."]) }
                        self.buffer.append(chunk)
                    }
                    let end=self.buffer.firstIndex(of:10)!;let reply=self.buffer.prefix(upTo:end);self.buffer.removeSubrange(...end)
                    continuation.resume(returning:Data(reply))
                } catch { continuation.resume(throwing:error) }
            }
        }
    }
    private func start() throws {
        let resources=Bundle.main.resourceURL!
        let runtime=resources.appendingPathComponent("Python.framework/Versions/3.12")
        let task=Process();task.executableURL=runtime.appendingPathComponent("bin/python3.12")
        task.arguments=["-B","-I",resources.appendingPathComponent("Engine/native/macos/bridge.py").path]
        var env=ProcessInfo.processInfo.environment
        env["PYTHONHOME"]=runtime.path;env["PYTHONNOUSERSITE"]="1";env["PYTHONDONTWRITEBYTECODE"]="1"
        env["SSL_CERT_FILE"]=resources.appendingPathComponent("cacert.pem").path
        env["DAGAMI_NATIVE_APP"]=Bundle.main.executablePath!
        env["DAGAMI_BUNDLED_ENGINE"]="1"
        task.environment=env
        let read=Pipe(),write=Pipe();task.standardInput=write;task.standardOutput=read;task.standardError=FileHandle.nullDevice
        try task.run();process=task;input=write.fileHandleForWriting;output=read.fileHandleForReading
    }
    deinit { try? input?.close();process?.terminate() }
}
@MainActor final class Model:ObservableObject {
    @Published var state=Snapshot();@Published var busy=false;@Published var message="Настройки сети под вашим контролем."
    @Published var profile="" {didSet{if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] != "1" {UserDefaults.standard.set(profile,forKey:"selectedProfile")}}}
    @Published var client="";@Published var ready=false;@Published var journal="Журнал пока пуст."
    @Published var auth=AuthState()
    @Published var clipboardEnabled=true;@Published var authNetworkStatus=""
    private let clipboard=OAuthClipboard()
    private var clipboardTimer:Timer?
    let rpc=RPC()
    init() {
        profile=UserDefaults.standard.string(forKey:"selectedProfile") ?? ""
        clipboardTimer=Timer.scheduledTimer(withTimeInterval:0.5,repeats:true){[weak self] _ in Task{@MainActor in self?.pollClipboard()}}
    }
    private func pollClipboard() {
        let active=clipboardEnabled && auth.running && auth.profile==profile
        guard active else{_ = clipboard.poll(enabled:false,service:auth.service ?? "");return}
        guard !busy,let service=auth.service else{return}
        if let url=clipboard.poll(enabled:true,service:service) {auth.url=url;auth.message="Ссылка из буфера получена. Проверяется маршрут входа…";run("authClipboard",["url":url,"service":service,"profile":profile],refresh:false)}
        else if !clipboard.rejection.isEmpty {auth.message=clipboard.rejection;message=clipboard.rejection}
    }
    func refresh() {
        if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
            state=Snapshot();state.activated=true;state.systemDNS="Применён";state.profiles=[Profile(id:"ai",name:"ИИ — Smart DNS",dns:true,proxy:false,endpoints:["udp://89.22.224.205"],scope:"ai",domains:[])]
            state.apps=[ClientApp(id:"antigravity",name:"Google Antigravity",path:"fixture",installed:true,prepared:false),ClientApp(id:"codex",name:"Codex CLI",path:"fixture",installed:true,prepared:false),ClientApp(id:"claude",name:"Claude Code",path:"fixture",installed:true,prepared:false)]
            state.services=[NetworkService(id:"Ethernet",name:"Ethernet"),NetworkService(id:"Wi-Fi",name:"Wi-Fi")];profile="ai";ready=true;return
        }
        run("snapshot",refresh:false)
    }
    func run(_ action:String,_ args:[String:Any]=[:],refresh:Bool=true) {
        guard !busy else{return};busy=true
        Task {
            do {
                let targetApp = (args["app"] as? String) ?? (action=="prepareAuth" ? "antigravity" : nil)
                if ["launch","prepare","restore","unpatch","prepareAuth","repairIDE"].contains(action),let app=targetApp {
                    let inspected=try await rpc.call("appInspect",["app":app])
                    let reply=try JSONSerialization.jsonObject(with:inspected) as! [String:Any]
                    if reply["ok"] as? Bool != true {throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:reply["error"] as? String ?? "Не удалось проверить процессы"])}
                    let result=reply["result"] as? [String:Any] ?? [:]
                    let processes=result["processes"] as? [[String:Any]] ?? []
                    if result["cli"] as? Bool != true && !processes.isEmpty {
                        let alert=NSAlert();alert.messageText="У вас открыты процессы ИИ-приложения"
                        let names=processes.prefix(12).map{($0["name"] as? String ?? "Процесс")+" (PID "+String($0["pid"] as? Int ?? 0)+")"}.joined(separator:"\n")
                        alert.informativeText="Сохраните несохранённые данные перед закрытием.\n\n"+names+"\n\nПродолжить после закрытия процессов?"
                        alert.addButton(withTitle:"Закрыть процессы");alert.addButton(withTitle:"Отменить")
                        if alert.runModal() != .alertFirstButtonReturn {busy=false;return}
                        let closed=try await rpc.call("appClose",["app":app]);let response=try JSONSerialization.jsonObject(with:closed) as! [String:Any]
                        if response["ok"] as? Bool != true {throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:response["error"] as? String ?? "Процессы не закрыты"])}
                    }
                }
                let bytes=try await rpc.call(action,args)
                let json=try JSONSerialization.jsonObject(with:bytes) as! [String:Any]
                if json["ok"] as? Bool != true { throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:json["error"] as? String ?? "Операция не завершена"]) }
                if action=="snapshot" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    state=try JSONDecoder().decode(Snapshot.self,from:data);ready=true
                    if !state.profiles.contains(where:{$0.id==profile}) { profile=state.profiles.first?.id ?? "" }
                    if !state.apps.contains(where:{$0.id==client}) { client=state.apps.first(where:{$0.installed})?.id ?? state.apps.first?.id ?? "" }
                } else if action=="probeAuth" {
                    authNetworkStatus=json["result"] as? String ?? "Проверка завершена"
                } else if action=="authFind" {
                    let value=json["result"] as? String ?? ""
                    if !value.isEmpty {auth.url=value;auth.message="Свежая ссылка найдена"} else {auth.message="Свежая ссылка не найдена. Начните вход в приложении."}
                } else if action.hasPrefix("auth") {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    auth=try JSONDecoder().decode(AuthState.self,from:data)
                    if action=="authStart" || action=="authStop" {clipboard.reset()}
                } else if action=="journal" {journal=json["result"] as? String ?? "Журнал пока пуст."
                } else {
                    message=(json["result"] as? String) ?? "Готово"
                }
                busy=false
                if refresh { self.refresh() }
            } catch { message=error.localizedDescription;if action=="authClipboard" {clipboard.reset()};if action.hasPrefix("auth") {auth.message=error.localizedDescription};if action=="probeAuth" {authNetworkStatus=error.localizedDescription};busy=false;ready=true }
        }
    }
    var chosen:Profile? {state.profiles.first{$0.id==profile}}
}
final class Delegate:NSObject,NSApplicationDelegate,NSWindowDelegate {
    func applicationDidFinishLaunching(_ notification:Notification) {
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
            NSApp.windows.first?.delegate=self
            if let path=ProcessInfo.processInfo.environment["DAGAMI_UI_SCREENSHOT"] {
                DispatchQueue.main.asyncAfter(deadline:.now()+2) {
                    if let view=NSApp.windows.first(where:{$0.frame.width>800})?.contentView,
                       let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds) {
                        view.cacheDisplay(in:view.bounds,to:rep)
                        try? rep.representation(using:.png,properties:[:])?.write(to:URL(fileURLWithPath:path))
                    }
                }
            }
            if CommandLine.arguments.contains("--autostart") { NSApp.hide(nil) }
        }
    }
    func windowShouldClose(_ sender:NSWindow)->Bool { sender.orderOut(nil);return false }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool)->Bool { NSApp.windows.first?.makeKeyAndOrderFront(nil);return true }
}
@main struct DagamiApp:App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    @StateObject var model=Model()
    var body:some Scene {
        WindowGroup { RootView().environmentObject(model).frame(minWidth:960,minHeight:680).onAppear{if !model.ready {model.refresh()}} }
            .windowStyle(.hiddenTitleBar).defaultSize(width:1100,height:760)
        MenuBarExtra("Dagami",systemImage:"network") {
            Button("Открыть Dagami"){NSApp.activate(ignoringOtherApps:true);NSApp.windows.first?.makeKeyAndOrderFront(nil)}
            Button("Проверить подключение"){model.run("check",["profile":model.profile])}.disabled(model.profile.isEmpty || model.busy)
            Divider();Button("Выход"){NSApp.terminate(nil)}
        }
    }
}
struct Card<Content:View>:View {
    @ViewBuilder var content:Content
    var body:some View { VStack(alignment:.leading,spacing:16){content}.padding(22).frame(maxWidth:.infinity,alignment:.leading).background(.background,in:RoundedRectangle(cornerRadius:20)).overlay(RoundedRectangle(cornerRadius:20).strokeBorder(.primary.opacity(0.06))).shadow(color:.black.opacity(0.025),radius:12,y:4) }
}
struct RootView:View {
    @EnvironmentObject var model:Model
    @State private var page="Обзор";@State private var editor=false;@State private var editProfile:Profile?
    let pages=[("Обзор","square.grid.2x2"),("Профили","slider.horizontal.3"),("Приложения","app.badge"),("Авторизация","person.crop.circle.badge.checkmark"),("DNS в системе","network"),("Журнал","list.bullet.rectangle"),("Настройки","gearshape")]
    var body:some View {
        Group {
            if !model.ready { ProgressView("Запускаем Dagami…").frame(maxWidth:.infinity,maxHeight:.infinity) }
            else if !model.state.activated { ActivationView() }
            else {
                HStack(spacing:0) {
                    VStack(alignment:.leading,spacing:22) {
                        HStack(spacing:10){Image(systemName:"network").font(.title).foregroundStyle(.blue);VStack(alignment:.leading){Text("Dagami").font(.title2.bold());Text("Agent Proxy").font(.caption).foregroundStyle(.secondary)}}.padding(.top,28).padding(.horizontal,18)
                        VStack(spacing:5){ForEach(pages,id:\.0){item in Button{page=item.0}label:{HStack(spacing:11){Image(systemName:item.1).frame(width:22);Text(item.0);Spacer()}.padding(.horizontal,13).padding(.vertical,11).foregroundStyle(page==item.0 ? Color.white:Color.primary).background(page==item.0 ? Color.accentColor:Color.clear,in:RoundedRectangle(cornerRadius:10))}.buttonStyle(.plain)}}.padding(.horizontal,12)
                        Spacer()
                        VStack(alignment:.leading,spacing:7){Label("macOS Universal",systemImage:"desktopcomputer").font(.caption);Text("Intel + Apple silicon").font(.caption2).foregroundStyle(.secondary)}.padding(20)
                    }.frame(width:220).background(Color(nsColor:.controlBackgroundColor))
                    Divider()
                    VStack(spacing:0) {
                        HStack { VStack(alignment:.leading,spacing:5){Text(page).font(.system(size:30,weight:.bold,design:.rounded));Text(subtitle).font(.subheadline).foregroundStyle(.secondary)};Spacer();if model.busy {ProgressView().controlSize(.small)};Button{model.refresh()}label:{Image(systemName:"arrow.clockwise")}.buttonStyle(.borderless).help("Обновить") }.padding(.horizontal,30).padding(.top,35).padding(.bottom,24)
                        ScrollView { VStack(spacing:20){pageContent}.padding(.horizontal,30).padding(.bottom,24) }
                        HStack(alignment:.top,spacing:10){Image(systemName:model.busy ? "hourglass":"info.circle").foregroundStyle(.blue);ScrollView{Text(model.message).font(.caption).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading)}.frame(maxHeight:64)}.padding(16).background(.bar)
                    }.background(Color(nsColor:.windowBackgroundColor))
                }.animation(.easeInOut(duration:0.2),value:page)
            }
        }
        .sheet(isPresented:$editor){ProfileSheet(profile:editProfile).environmentObject(model)}
    }
    var subtitle:String {switch page {case "Обзор":return "Подключение, которое вы выбираете.";case "Профили":return "Smart DNS, прокси или их привычные настройки.";case "Приложения":return "Запускайте нужные инструменты одним нажатием.";case "DNS в системе":return "Настройки сети macOS с резервной копией и откатом.";default:return "Всё необходимое. Ничего лишнего."}}
    @ViewBuilder var pageContent:some View {
        switch page {
        case "Профили":profiles
        case "Приложения":AppsView()
        case "DNS в системе":SystemDNSView()
        case "Настройки":settings
        case "Журнал":JournalView()
        case "Авторизация":AuthView()
        default:overview
        }
    }
    var overview:some View {
        VStack(spacing:20){
            Card {
                HStack(alignment:.top){ZStack{RoundedRectangle(cornerRadius:18).fill(.blue.opacity(0.1)).frame(width:64,height:64);Image(systemName:"network").font(.system(size:30)).foregroundStyle(.blue)};VStack(alignment:.leading,spacing:8){Text(model.chosen?.name ?? "Создайте первый профиль").font(.title2.bold());Text(model.chosen?.subtitle ?? "Выберите DNS без пароля или вставьте ссылку прокси.").foregroundStyle(.secondary)};Spacer();Text("ГОТОВ К ЗАПУСКУ").font(.system(size:9,weight:.bold)).tracking(1).padding(8).background(.blue.opacity(0.08),in:Capsule()).foregroundStyle(.blue)}
                if !model.state.profiles.isEmpty {Picker("Профиль",selection:$model.profile){ForEach(model.state.profiles){Text($0.name).tag($0.id)}}}
                HStack{Button("Проверить подключение"){model.run("check",["profile":model.profile])}.buttonStyle(.borderedProminent).disabled(model.profile.isEmpty || model.busy);Button("Новый профиль"){editProfile=nil;editor=true}.buttonStyle(.bordered)}
            }
            HStack(alignment:.top,spacing:16){Card{Label("DNS в системе",systemImage:"globe").font(.headline);Text(model.state.systemDNS).font(.title3.weight(.medium));Button("Настроить DNS macOS"){page="DNS в системе"}.buttonStyle(.borderless)};Card{Label("Ваши приложения",systemImage:"app.connected.to.app.below.fill").font(.headline);Text("\(model.state.apps.filter{$0.installed}.count) найдено").font(.title3.weight(.medium));Button("Открыть приложения"){page="Приложения"}.buttonStyle(.borderless)}}
            AppsView(compact:true)
        }
    }
    var profiles:some View {
        VStack(spacing:16){HStack{Text("\(model.state.profiles.count) профилей").foregroundStyle(.secondary);Spacer();Button{editProfile=nil;editor=true}label:{Label("Добавить",systemImage:"plus")}.buttonStyle(.borderedProminent)}
            if model.state.profiles.isEmpty {Card{Image(systemName:"slider.horizontal.3").font(.largeTitle).foregroundStyle(.blue);Text("Начните с подключения").font(.title2.bold());Text("Для DNS-профиля не нужны логин и пароль.").foregroundStyle(.secondary)}}
            ForEach(model.state.profiles){profile in Card{HStack{Image(systemName:profile.dns ? "globe":"lock.shield").font(.title2).foregroundStyle(.blue);VStack(alignment:.leading,spacing:5){Text(profile.name).font(.headline);Text(profile.subtitle).font(.subheadline).foregroundStyle(.secondary)};Spacer();if model.profile==profile.id {Image(systemName:"checkmark.circle.fill").foregroundStyle(.blue)}};HStack{Button("Выбрать"){model.profile=profile.id};Button("Изменить"){editProfile=profile;editor=true};Spacer();Text(profile.endpoints.first ?? "Прокси из ссылки").font(.caption).foregroundStyle(.secondary)}}}
        }
    }
    var settings:some View {
        VStack(spacing:20){LicenseSettingsView();Card{Label("При входе в систему",systemImage:"power").font(.headline);Toggle("Запускать Dagami вместе с macOS",isOn:Binding(get:{model.state.startup},set:{model.run("startup",["enabled":$0])})).disabled(model.busy);Text("Настройка использует пользовательский LaunchAgent.").font(.caption).foregroundStyle(.secondary)}
            Card{Text("Dagami Agent Proxy").font(.title2.bold());Text("Нативный интерфейс · Universal · 0.4.0 mac.24").foregroundStyle(.secondary);HStack{Link("Поддержка",destination:URL(string:"https://t.me/dagamvi")!);Link("Сообщить об ошибке",destination:URL(string:"https://dns.dagami.ru/support/agent-proxy/")!)};HStack{Link("Официальный репозиторий",destination:URL(string:"https://github.com/j46871417-ui/Dagami-Agent-Proxy")!);Link("Портер на Mac — ImRealDerli",destination:URL(string:"https://github.com/ImRealDerli")!)}.buttonStyle(.bordered)}
        }
    }
}
struct ActivationView:View {
    @EnvironmentObject var model:Model;@State var key=""
    var body:some View {VStack(spacing:22){Image(systemName:"network").font(.system(size:60)).foregroundStyle(.blue);Text("Добро пожаловать в Dagami").font(.system(size:30,weight:.bold,design:.rounded));Text("Ваши приложения. Ваш маршрут.").foregroundStyle(.secondary);SecureField("Ключ доступа DAGAMI-…",text:$key).textFieldStyle(.roundedBorder).frame(width:360);Button("Продолжить"){model.run("activate",["key":key]);key=""}.buttonStyle(.borderedProminent).controlSize(.large).disabled(key.isEmpty || model.busy);Link("Получить бесплатный ключ",destination:URL(string:"https://t.me/bright26bot?start=dagami")!);if model.busy {ProgressView()};Text(model.message).font(.caption).foregroundStyle(.secondary).frame(maxWidth:500)}.frame(maxWidth:.infinity,maxHeight:.infinity).background(.regularMaterial)}
}
struct ProfileSheet:View {
    @EnvironmentObject var model:Model;@Environment(\.dismiss) var dismiss
    var profile:Profile?
    @State var name="";@State var mode="DNS";@State var provider="Dagami UDP";@State var endpoints="udp://89.22.224.205";@State var domains="";@State var scope="ai";@State var url=""
    var body:some View {
        VStack(alignment:.leading,spacing:20){HStack{Text(profile == nil ? "Новый профиль":"Изменить профиль").font(.title2.bold());Spacer();Button{dismiss()}label:{Image(systemName:"xmark.circle.fill").foregroundStyle(.secondary)}.buttonStyle(.plain)}
            TextField("Название профиля",text:$name).textFieldStyle(.roundedBorder).disabled(profile != nil)
            Picker("Тип подключения",selection:$mode){Text("Smart DNS").tag("DNS");Text("Прокси").tag("Proxy")}.pickerStyle(.segmented)
            if mode=="DNS" {
                Text("Без логина и пароля. Для приложений, запущенных через Dagami; DNS всей системы настраивается отдельно.").font(.callout).foregroundStyle(.secondary)
                Picker("Провайдер",selection:$provider){Text("Dagami · UDP").tag("Dagami UDP");Text("MagicDNS · UDP").tag("MagicDNS UDP");ForEach(model.state.providers.keys.sorted(),id:\.self){Text($0).tag($0)};Text("Свой DNS").tag("Custom")}.onChange(of:provider){value in if value=="Dagami UDP" {endpoints="udp://89.22.224.205"} else if value=="MagicDNS UDP" {endpoints="udp://2.56.175.196"} else if let list=model.state.providers[value] {endpoints=list.joined(separator:"\n")} }
                TextEditor(text:$endpoints).font(.system(.body,design:.monospaced)).frame(height:65).padding(6).background(.quaternary,in:RoundedRectangle(cornerRadius:8))
                Picker("Домены",selection:$scope){Text("Все ИИ").tag("ai");Text("Google / Antigravity").tag("google")}
                Text("ChatGPT, Claude, Gemini, DeepSeek, Qwen, Grok, Perplexity и другие. Доступность зависит от DNS-провайдера.").font(.caption).foregroundStyle(.secondary)
                TextField("Свои домены через запятую, например *.example.ai",text:$domains).textFieldStyle(.roundedBorder)
            } else {Text("Вставьте полную ссылку — протокол, адрес, порт и реквизиты сохранятся вместе.").foregroundStyle(.secondary);SecureField("https://логин:пароль@сервер:порт",text:$url).textFieldStyle(.roundedBorder);Text("Пароль сохраняется в Связке ключей macOS.").font(.caption).foregroundStyle(.secondary)}
            Divider();HStack{Button("Отмена"){dismiss()};Spacer();Button("Сохранить"){let args:[String:Any];let action:String;if mode=="DNS" {action="saveDNS";args=["name":name,"endpoints":endpoints.split(separator:"\n").map(String.init),"scope":scope,"domains":domains.components(separatedBy:",").map{$0.trimmingCharacters(in:.whitespacesAndNewlines)}.filter{!$0.isEmpty},"replace":profile != nil]} else {action="saveProxy";args=["name":name,"url":url,"replace":profile != nil]};model.profile=name;model.run(action,args);dismiss()}.buttonStyle(.borderedProminent).disabled(name.trimmingCharacters(in:.whitespaces).isEmpty || (mode=="Proxy" && url.isEmpty) || model.busy)}
        }.padding(28).frame(width:560).onAppear{if let p=profile {name=p.name;mode=p.dns && !p.proxy ? "DNS":"Proxy";endpoints=p.endpoints.joined(separator:"\n");scope=p.scope;domains=p.domains.joined(separator:", ");provider="Custom"} else {name="ИИ — Smart DNS"}}
    }
}
struct AppsView:View {
    @EnvironmentObject var model:Model
    var compact=false
    @State var search="";@State var login=false;@State var loginURL="";@State var choose=true
    var apps:[ClientApp] {let list=compact ? model.state.apps.filter{$0.installed}:model.state.apps;return list.filter{search.isEmpty || $0.name.localizedCaseInsensitiveContains(search)}}
    var body:some View {
        Card {
            HStack{Text(compact ? "Быстрый запуск":"Приложения").font(.headline);Spacer();if !compact {Button{let panel=NSOpenPanel();panel.canChooseFiles=true;panel.canChooseDirectories=true;panel.allowsMultipleSelection=false;if panel.runModal() == .OK,let path=panel.url?.path {model.run("addApp",["path":path,"cli":!path.contains(".app")])}}label:{Image(systemName:"plus")}.help("Добавить приложение")}}
            if !compact {TextField("Найти приложение",text:$search).textFieldStyle(.roundedBorder)}
            if apps.isEmpty {Text("Приложения пока не найдены. Добавьте .app или исполняемый файл.").foregroundStyle(.secondary)}
            ForEach(apps){app in
                HStack(spacing:12){Image(systemName:app.id.contains("codex") ? "terminal":"app").font(.title2).foregroundStyle(.blue).frame(width:36);VStack(alignment:.leading,spacing:4){Text(app.name).font(.headline);Text(app.installed ? "Найдено на этом Mac":"Укажите путь к приложению").font(.caption).foregroundStyle(.secondary);if let reason=app.launchError {Text(reason).font(.caption).foregroundStyle(.orange).fixedSize(horizontal:false,vertical:true)}};Spacer();if ["antigravity","antigravity-ide","agy","codex","codex-gui","chatgpt"].contains(app.id) {Button(app.prepared ? "Откат":"Патч"){model.run(app.prepared ? "restore":"prepare",["app":app.id,"profile":model.profile])}.disabled(!app.installed || model.busy || (app.launchError != nil && !app.prepared))};if app.id=="chatgpt" {Button("Веб-версия"){model.run("launch",["app":"chatgpt-web","profile":model.profile])}.disabled(model.profile.isEmpty || model.busy)};Button("Запустить"){model.client=app.id;model.run("launch",["app":app.id,"profile":model.profile])}.buttonStyle(.borderedProminent).disabled(!app.installed || app.launchError != nil || model.profile.isEmpty || model.busy)
                    if ["antigravity","antigravity-ide"].contains(app.id) {Button("Починить IDE"){model.run("repairIDE",["app":app.id,"profile":model.profile])}.disabled((!app.installed && !app.prepared) || model.busy)}
                    Menu {Button("Остановить сессию"){let alert=NSAlert();alert.messageText="Остановить \(app.name)?";alert.informativeText="Сохраните работу. Будут закрыты управляемые процессы приложения.";alert.addButton(withTitle:"Остановить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("stop",["app":app.id])}};Button("Создать запуск через Dagami"){model.run("shortcut",["app":app.id,"profile":model.profile])};Button("Отменить подготовку"){model.run("unpatch",["app":app.id])};if ["antigravity","antigravity-ide"].contains(app.id) {Button("Подготовить backend"){model.run("prepare",["app":app.id,"profile":model.profile])};Button("Проверить сервер IDE"){model.run("checkIDE",["profile":model.profile])};Button("Вход Google"){model.client=app.id;login=true}};if app.id.hasPrefix("custom_"){Button("Удалить запись"){model.run("removeApp",["app":app.id])}} } label:{Image(systemName:"ellipsis").frame(width:20)}.menuStyle(.borderlessButton).fixedSize().disabled(model.busy)
                }.padding(.vertical,8)
                if app.id != apps.last?.id {Divider()}
            }
        }.sheet(isPresented:$login){VStack(alignment:.leading,spacing:20){Text("Вход Google").font(.title2.bold());Text("Начните вход в Antigravity и вставьте свежую ссылку accounts.google.com. Она откроется через активную сессию приложения.").foregroundStyle(.secondary);SecureField("Ссылка входа",text:$loginURL).textFieldStyle(.roundedBorder);Toggle("Предложить выбор аккаунта",isOn:$choose);HStack{Button("Отмена"){login=false};Button("Найти ссылку"){Task{if let data=try? await model.rpc.call("loginURL"),let reply=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {loginURL=reply["result"] as? String ?? ""}}};Button("Копировать"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(loginURL,forType:.string)}.disabled(loginURL.isEmpty);Spacer();Button("Открыть вход"){model.run("login",["app":model.client,"url":loginURL,"choose":choose]);login=false;loginURL=""}.buttonStyle(.borderedProminent).disabled(loginURL.isEmpty)}}.padding(28).frame(width:500)}
    }
}
struct SystemDNSView:View {
    @EnvironmentObject var model:Model
    @State var server="89.22.224.205";@State var mode="domains";@State var services=Set<String>();@State var replace=false
    var body:some View {VStack(spacing:20){Card{HStack{Image(systemName:"network").font(.largeTitle).foregroundStyle(.blue);VStack(alignment:.leading,spacing:5){Text("DNS в macOS").font(.title2.bold());Text("Текущее состояние: \(model.state.systemDNS)").foregroundStyle(.secondary)}};Text("Рекомендуется режим «Только домены ИИ»: обычные сайты используют DNS вашей сети. Изменения применяются к сети Mac. Перед записью сохраняется копия; для изменения настроек macOS запросит права администратора.").font(.callout).foregroundStyle(.secondary)
            Button("Исправить загрузку страниц в браузере"){let alert=NSAlert();alert.messageText="Разделить DNS для ИИ и обычных сайтов?";alert.informativeText="Прежний общий DNS будет восстановлен из копии. Если выбранный Smart DNS всё ещё является единственным общим сервером, подключение вернётся к автоматическому DNS сети. Для доменов ИИ сохранятся отдельные правила. macOS запросит права администратора.";alert.addButton(withTitle:"Исправить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("systemDNS",["operation":"apply","server":server,"mode":"domains","services":[],"replace":replace,"restore_global":true])}}.buttonStyle(.borderedProminent).disabled(model.busy)
            TextField("IP DNS-сервера",text:$server).textFieldStyle(.roundedBorder)
            Picker("Режим",selection:$mode){Text("Выбранные подключения").tag("adapters");Text("Только домены ИИ").tag("domains")}.pickerStyle(.segmented)
            if mode=="adapters" {ForEach(model.state.services){service in Toggle(service.name,isOn:Binding(get:{services.contains(service.id)},set:{if $0 {services.insert(service.id)} else {services.remove(service.id)}}))};if model.state.services.isEmpty{Text("Подключения не найдены. Нажмите обновление.").foregroundStyle(.secondary)}}
            Toggle("Разрешить замену конфликтующих правил с копией",isOn:$replace)
            HStack{Button("Применить DNS"){let alert=NSAlert();alert.messageText="Применить DNS к macOS?";alert.informativeText="Сервер: \(server). Выбранные подключения: \(services.sorted().joined(separator:", ")). macOS запросит права администратора.";alert.addButton(withTitle:"Применить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("systemDNS",["operation":"apply","server":server,"mode":mode,"services":Array(services),"replace":replace,"restore_global":mode=="domains"])}}.buttonStyle(.borderedProminent).disabled(model.busy || (mode=="adapters" && services.isEmpty));Button("Восстановить прежний DNS"){model.run("systemDNS",["operation":"restore"])}.disabled(model.busy)}
        };Card{Label("Ethernet и Wi-Fi",systemImage:"cable.connector").font(.headline);Text("Список считывается из macOS. Для общего DNS отметьте реальное подключение, через которое работает интернет. Профиль Smart DNS и системный DNS настраиваются отдельно.").foregroundStyle(.secondary)}}}
}

struct JournalView:View {
    @EnvironmentObject var model:Model
    var body:some View {Card{HStack{Label("Журнал событий",systemImage:"list.bullet.rectangle").font(.headline);Spacer();Button("Обновить"){model.run("journal",refresh:false)}.disabled(model.busy);Button("Копировать"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(model.journal,forType:.string)}};Text("Операции, проверки подключения и ошибки. Ошибки содержат полный traceback и stderr. Пароли и параметры ссылок входа скрываются.").font(.caption).foregroundStyle(.secondary);ScrollView{Text(model.journal).font(.system(.caption,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading)}.frame(minHeight:370)}.onAppear{model.run("journal",refresh:false)}}
}

struct LicenseSettingsView:View {
    @EnvironmentObject var model:Model
    @State var key=""
    var body:some View {Card{
        Label("Активация Dagami",systemImage:"key.horizontal").font(.headline)
        Text(model.state.activated ? "Ключ активирован":"Нужна активация").foregroundStyle(.secondary)
        SecureField("Новый ключ доступа DAGAMI-…",text:$key).textFieldStyle(.roundedBorder)
        HStack{Button("Активировать ключ"){model.run("activate",["key":key]);key=""}.disabled(key.isEmpty || model.busy)
            Button("Сбросить ключ",role:.destructive){let alert=NSAlert();alert.messageText="Сбросить ключ активации Dagami?";alert.informativeText="После сброса потребуется повторная активация. Текущая сессия входа через браузер будет закрыта. Профили, пароли прокси и аккаунты ИИ сохранятся.";alert.addButton(withTitle:"Сбросить ключ");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("licenseReset")}}.disabled(model.busy)
        }.buttonStyle(.bordered)
        Link("Получить ключ",destination:URL(string:"https://t.me/bright26bot?start=dagami")!)
    }}
}

struct AuthView:View {
    @EnvironmentObject var model:Model
    @State var service="codex";@State var mode="cli";@State var auto=true;@State var inputURL=""
    let services=[("codex","Codex / ChatGPT"),("claude","Claude / Claude Code"),("antigravity","Antigravity App"),("antigravity-ide","Antigravity IDE — VS Code"),("agy","Antigravity CLI"),("gemini","Gemini / Google AI"),("deepseek","DeepSeek"),("qwen","Qwen"),("grok","Grok"),("perplexity","Perplexity"),("mistral","Mistral"),("copilot","Microsoft Copilot"),("openrouter","OpenRouter"),("custom","Другой ИИ — своя ссылка")]
    func start() {
        if model.auth.running {
            let alert=NSAlert();alert.messageText="Начать новую сессию входа?";alert.informativeText="Предыдущий браузер входа будет закрыт. Сохранённые аккаунты клиентов не удаляются.";alert.addButton(withTitle:"Начать");alert.addButton(withTitle:"Отмена");if alert.runModal() != .alertFirstButtonReturn {return}
        }
        model.run("authStart",["service":service,"profile":model.profile,"mode":mode,"auto":auto,"url":service=="custom" ? inputURL:""] ,refresh:false)
    }
    var body:some View {VStack(spacing:20){
        Card{
            Label("Вход через выбранный профиль",systemImage:"person.crop.circle.badge.checkmark").font(.headline)
            Picker("Профиль",selection:$model.profile){ForEach(model.state.profiles){Text($0.name).tag($0.id)}}
            Picker("ИИ-сервис",selection:$service){ForEach(services,id:\.0){Text($0.1).tag($0.0)}}.onChange(of:service){value in mode=(value=="codex" || value=="claude") ? "cli":((value=="antigravity" || value=="antigravity-ide" || value=="agy") ? "watch":"browser");inputURL=""}
            Button("Проверить маршрут входа"){model.run("probeAuth",["profile":model.profile,"service":service,"url":service=="custom" ? inputURL:""],refresh:false)}.disabled(model.profile.isEmpty || model.busy)
            if !model.authNetworkStatus.isEmpty {Text(model.authNetworkStatus).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)}
            Toggle("Подхватывать OAuth-ссылки из буфера обмена",isOn:$model.clipboardEnabled)
            Text("Работает только во время ожидания входа и только для выбранного профиля. Принимаются исходные OAuth-ссылки с проверенным доменом, client_id, state и callback. Адреса accountchooser/consent из браузера не открываются повторно.").font(.caption).foregroundStyle(.secondary)
            if service=="agy" {Text("Откройте CLI кнопкой ниже. Selenium получит код с официальной страницы возврата и передаст его в ожидающий CLI с Enter. Состояние OAuth проверяется; ручной ввод не перезаписывается.").font(.callout).foregroundStyle(.secondary)}
            if service=="agy" {Button("Открыть CLI с перехватом входа"){model.run("launch",["app":"agy","profile":model.profile])}.buttonStyle(.borderedProminent).disabled(model.profile.isEmpty || model.busy)}
            Picker("Способ входа",selection:$mode){if service != "antigravity" && service != "antigravity-ide" && service != "agy" {Text("Сайт в браузере").tag("browser")};if service=="codex" || service=="claude" {Text("Штатный вход CLI").tag("cli")};if service=="codex" {Text("Код устройства").tag("device")};if service != "custom" {Text(["antigravity","antigravity-ide"].contains(service) ? "Вход в Antigravity":"Подхват из приложения").tag("watch")}}
            if service != "agy" {Text(mode=="cli" ? "Dagami запустит штатную команду входа клиента, подхватит ссылку и откроет её через тот же профиль. Вход завершается в самом клиенте.":(mode=="device" ? "Для Codex может потребоваться включить вход по коду устройства в настройках безопасности ChatGPT.":(["antigravity","antigravity-ide"].contains(service) ? "Для входа IDE нужна её собственная свежая ссылка. Dagami откроет её через профиль активной сессии.":(mode=="watch" ? "Нажмите «Начать вход», затем начните авторизацию в IDE или CLI. Новые ссылки из поддерживаемых журналов будут подхвачены автоматически в течение 10 минут.":"Веб-вход создаёт сессию в отдельном браузере. Для входа CLI выберите штатный вход CLI.")))).font(.callout).foregroundStyle(.secondary)}
            if ["antigravity","antigravity-ide"].contains(service) {
                Text("Сначала один раз настройте вход в IDE. Затем нажмите «Начать вход» здесь и «Войти» в Antigravity. Ссылка откроется через маршрут самой IDE.").font(.callout).foregroundStyle(.secondary)
                Button("Настроить вход в IDE") {model.run("prepareAuth",["profile":model.profile,"app":service])}.disabled(model.profile.isEmpty || model.busy)
            }
            if !["antigravity","antigravity-ide"].contains(service) {Toggle("Автоматически открывать найденную ссылку",isOn:$auto)}
            if service=="custom" {TextField("HTTPS-ссылка страницы входа",text:$inputURL).textFieldStyle(.roundedBorder);Text("Проверьте домен сервиса перед входом.").font(.caption).foregroundStyle(.secondary)}
            HStack{if service != "agy" {Button("Начать вход"){start()}.buttonStyle(.borderedProminent).disabled(model.profile.isEmpty || model.busy || (service=="custom" && inputURL.isEmpty))};Button("Остановить сессию"){model.run("authStop",refresh:false)}.disabled(!model.auth.running || model.busy)}
        }
        Card{
            Text("Ссылка авторизации").font(.headline)
            SecureField("Свежая ссылка из клиента или браузера",text:$inputURL).textFieldStyle(.roundedBorder)
            HStack{Button("Найти ссылку"){model.run("authFind",["service":service,"profile":model.profile],refresh:false)}.disabled(service=="custom" || model.busy);Button("Открыть через профиль"){if model.auth.running && model.auth.service==service && model.auth.profile==model.profile {model.run("authOpen",["url":inputURL],refresh:false)} else {model.run("authStart",["service":service,"profile":model.profile,"mode":"browser","auto":auto,"url":inputURL],refresh:false)}}.disabled(inputURL.isEmpty || model.profile.isEmpty || model.busy);Button("Копировать"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(inputURL,forType:.string)}.disabled(inputURL.isEmpty)}
            if !model.auth.code.isEmpty {Text("Код устройства: "+model.auth.code).font(.system(.title3,design:.monospaced)).textSelection(.enabled)}
            if let activeProfile=model.auth.profile,model.auth.running {Text("Маршрут активной сессии: "+activeProfile).font(.caption).foregroundStyle(.secondary)}
            Text(model.auth.message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            Text("Пароли вводятся только на сайте сервиса. Ссылки и коды входа не записываются в журнал Dagami. Доступ к модели проверяется отдельно.").font(.caption).foregroundStyle(.secondary)
        }
    }.onAppear{if ["antigravity","antigravity-ide","agy"].contains(model.client){service=model.client;mode="watch"}}.onChange(of:model.auth.url){value in if !value.isEmpty {inputURL=value}}
    .task{while !Task.isCancelled {do{try await Task.sleep(nanoseconds:2_000_000_000)}catch{return};if model.auth.running && !model.busy {model.run("authStatus",refresh:false)}}}
    }
}
