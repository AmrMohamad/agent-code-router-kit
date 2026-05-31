import Foundation

final class ResolverUsage {
    func makeRouter() -> ExampleRouting? {
        Resolver.resolve(ExampleRouter.self)
    }

    func makeService() -> ExampleService? {
        Resolver.resolve(ExampleService.self)
    }

    func makeViewModel() -> ExampleViewModel? {
        Resolver.resolve(ExampleViewModel.self)
    }
}
