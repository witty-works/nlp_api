require 'rubygems'
require 'active_support/all'
require 'yaml'

class FakeConfig
  def after_initialize
  end
  def development?
    false
  end
end

module Rails
  class Railtie
    def self.rake_tasks
      yield
    end

    def self.initializer(*args)
    end

    def self.config
      ::FakeConfig.new
    end
  end

  def self.env
    ::FakeConfig.new
  end
end

task :environment do
end

require 'translation'

I18n.load_path += Dir[File.join('i18n', '**', '*.{yml,yaml}')]

# Put your configuration here:
TranslationIO.configure do |config|
  config.yaml_locales_path = 'locales'
  config.api_key           = '7b70c7462d4f4866bc513e9b746cb3d9'
  config.source_locale     = 'en'
  config.target_locales    = ['de']
  config.metadata_path     = 'i18n/.translation_io'
end