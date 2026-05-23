import Foundation

protocol ExampleRouting {
    func openExample()
}

final class ExampleRouter: ExampleRouting {
    static let routeKey = "exampleRouteKey"

    func openExample() {
        let service: ExampleService? = Resolver.resolve(ExampleService.self)
        _ = Example.resolve(service)
    }
}

final class ExampleViewModel {
    private let router: ExampleRouting

    init(router: ExampleRouting = ExampleRouter()) {
        self.router = router
    }

    func start() {
        router.openExample()
    }
}

enum Example {
    static func resolve<T>(_ value: T?) -> T? {
        value
    }
}

enum Resolver {
    static func resolve<T>(_ type: T.Type) -> T? {
        nil
    }
}

final class ExampleService: NSObject {
    @objc func refreshFromSelector() {}

    func wireSelector() -> Selector {
        #selector(refreshFromSelector)
    }
}
