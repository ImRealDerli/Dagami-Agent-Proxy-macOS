import AppKit
import Foundation

final class OAuthClipboard {
    private let board:NSPasteboard
    private var change:Int
    private var lastURL=""
    private(set) var rejection=""
    init(board:NSPasteboard = .general) { self.board=board;change=board.changeCount }
    func reset() {change=board.changeCount;lastURL=""}
    static func candidate(_ value:String,service:String)->String? {
        guard value.utf8.count<=16384,let parts=URLComponents(string:value),parts.scheme=="https",parts.user==nil,parts.password==nil,parts.port==nil || parts.port==443,let host=parts.host else{return nil}
        let hosts:[String:[String]]=["antigravity-ide":["accounts.google.com","antigravity.google","antigravity.google.com"],"antigravity":["accounts.google.com","antigravity.google","antigravity.google.com"],"agy":["accounts.google.com"],"gemini":["accounts.google.com"],"codex":["auth.openai.com","accounts.google.com"],"claude":["claude.ai","claude.com","console.anthropic.com","platform.claude.com","accounts.google.com"]]
        guard hosts[service]?.contains(host)==true,parts.path.lowercased().range(of:"auth|login|signin|authorize",options:.regularExpression) != nil else{return nil}
        if host=="accounts.google.com" && !["/o/oauth2/auth","/o/oauth2/v2/auth"].contains(parts.path) {return nil}
        let query=parts.queryItems ?? []
        guard query.filter({$0.name=="state" && !($0.value ?? "").isEmpty}).count==1,query.filter({$0.name=="client_id" && !($0.value ?? "").isEmpty}).count==1 else{return nil}
        return value
    }
    func poll(enabled:Bool,service:String)->String? {
        rejection=""
        guard enabled else{reset();return nil}
        guard change != board.changeCount else{return nil}
        change=board.changeCount
        guard let raw=board.string(forType:.string) else{return nil}
        let cleaned=raw.trimmingCharacters(in:.whitespacesAndNewlines)
        if let parts=URLComponents(string:cleaned),parts.host=="accounts.google.com",!["/o/oauth2/auth","/o/oauth2/v2/auth"].contains(parts.path) {
            rejection="Промежуточная страница Google не подходит для нового входа. Нажмите «Войти» в клиенте заново; нужен исходный OAuth-запрос."
            return nil
        }
        guard let value=Self.candidate(cleaned,service:service),value != lastURL else{return nil}
        lastURL=value;return value
    }
}
