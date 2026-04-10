'use client'

import { useState } from 'react'
import { Menu, X, Phone, MapPin, Calendar } from 'lucide-react'

export default function Header() {
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  const navItems = [
    { label: 'Início', href: '#home' },
    { label: 'Estrutura', href: '#features' },
    { label: 'Fotos', href: '#gallery' },
    { label: 'Agenda', href: '#calendar' },
    { label: 'Como Reservar', href: '#how-to' },
    { label: 'Contrato', href: '#contract' },
  ]

  return (
    <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-gray-100 shadow-sm">
      <div className="container-custom px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-20">
          {/* Logo */}
          <div className="flex items-center space-x-3">
            <div className="bg-primary-600 text-white p-2 rounded-lg">
              <Calendar size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 font-display">DF Festas</h1>
              <p className="text-sm text-gray-600">Espaço completo com piscina</p>
            </div>
          </div>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex items-center space-x-8">
            {navItems.map((item) => (
              <a
                key={item.label}
                href={item.href}
                className="text-gray-700 hover:text-primary-600 font-medium transition-colors"
              >
                {item.label}
              </a>
            ))}
          </nav>

          {/* CTA Button & Contact */}
          <div className="hidden md:flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-gray-600">
              <MapPin size={18} />
              <span className="text-sm">Cachambi, RJ</span>
            </div>
            <a
              href="https://wa.me/5521999999999?text=Olá! Gostaria de saber mais sobre o DF Festas"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary flex items-center space-x-2"
            >
              <Phone size={18} />
              <span>Falar com atendente</span>
            </a>
          </div>

          {/* Mobile menu button */}
          <button
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className="md:hidden p-2 rounded-lg text-gray-700 hover:bg-gray-100"
          >
            {isMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Navigation */}
        {isMenuOpen && (
          <div className="md:hidden py-4 border-t border-gray-100 animate-slide-up">
            <div className="flex flex-col space-y-4">
              {navItems.map((item) => (
                <a
                  key={item.label}
                  href={item.href}
                  className="text-gray-700 hover:text-primary-600 py-2 font-medium"
                  onClick={() => setIsMenuOpen(false)}
                >
                  {item.label}
                </a>
              ))}
              <div className="pt-4 border-t border-gray-100">
                <div className="flex items-center space-x-2 text-gray-600 mb-4">
                  <MapPin size={18} />
                  <span>Cachambi, Rio de Janeiro - RJ</span>
                </div>
                <a
                  href="https://wa.me/5521999999999?text=Olá! Gostaria de saber mais sobre o DF Festas"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-primary w-full flex items-center justify-center space-x-2"
                >
                  <Phone size={18} />
                  <span>Falar no WhatsApp</span>
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </header>
  )
}