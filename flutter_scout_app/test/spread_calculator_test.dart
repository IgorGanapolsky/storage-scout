import 'package:flutter_test/flutter_test.dart';
import 'package:storage_scout/models/spread_calculator.dart';

void main() {
  group('SpreadCalculator', () {
    test('calculates positive spread with standard rates', () {
      final calc = SpreadCalculator(
        neighborRate: 65.0,
        commercialPrice: 150.0,
        hasInsuranceWaiver: false,
      );
      // (65 × 4) - 150 - 12 = 260 - 162 = 98
      expect(calc.spread, equals(98.0));
      expect(calc.revenue, equals(260.0));
      expect(calc.cost, equals(162.0));
      expect(calc.isProfitable, isTrue);
      expect(calc.isHighPriority, isFalse);
    });

    test('calculates spread with insurance waiver', () {
      final calc = SpreadCalculator(
        neighborRate: 65.0,
        commercialPrice: 150.0,
        hasInsuranceWaiver: true,
      );
      // (65 × 4) - 150 - 0 = 260 - 150 = 110
      expect(calc.spread, equals(110.0));
      expect(calc.cost, equals(150.0));
    });

    test('calculates negative spread when commercial too expensive', () {
      final calc = SpreadCalculator(
        neighborRate: 50.0,
        commercialPrice: 250.0,
      );
      // (50 × 4) - 250 - 12 = 200 - 262 = -62
      expect(calc.spread, equals(-62.0));
      expect(calc.isProfitable, isFalse);
      expect(calc.isHighPriority, isFalse);
    });

    test('detects high priority deals', () {
      final calc = SpreadCalculator(
        neighborRate: 75.0,
        commercialPrice: 150.0,
        hasInsuranceWaiver: true,
      );
      // (75 × 4) - 150 - 0 = 300 - 150 = 150
      expect(calc.spread, equals(150.0));
      expect(calc.isHighPriority, isTrue);
    });

    test('120 is exactly high priority threshold', () {
      // (x * 4) - 150 = 120 => x = 67.5
      final calc = SpreadCalculator(
        neighborRate: 67.5,
        commercialPrice: 150.0,
        hasInsuranceWaiver: true,
      );
      expect(calc.spread, equals(120.0));
      expect(calc.isHighPriority, isTrue);
    });

    test('119.99 is not high priority', () {
      // Need: (x * 4) - 150 = 119.99 => x = 67.4975
      final calc = SpreadCalculator(
        neighborRate: 67.4975,
        commercialPrice: 150.0,
        hasInsuranceWaiver: true,
      );
      expect(calc.spread, closeTo(119.99, 0.01));
      expect(calc.isHighPriority, isFalse);
    });

    test('handles zero commercial price', () {
      final calc = SpreadCalculator(
        neighborRate: 65.0,
        commercialPrice: 0.0,
      );
      // (65 × 4) - 0 - 12 = 260 - 12 = 248
      expect(calc.spread, equals(248.0));
    });

    test('handles zero P2P rate', () {
      final calc = SpreadCalculator(
        neighborRate: 0.0,
        commercialPrice: 150.0,
      );
      // (0 × 4) - 150 - 12 = -162
      expect(calc.spread, equals(-162.0));
    });

    test('insurance constant is 12 dollars', () {
      expect(SpreadCalculator.floridaInsurance, equals(12.0));
    });

    test('high priority threshold is 120 dollars', () {
      expect(SpreadCalculator.highPriorityThreshold, equals(120.0));
    });
  });

  group('InputValidator', () {
    group('isValidZipCode', () {
      test('accepts valid 5-digit zip codes', () {
        expect(InputValidator.isValidZipCode('33071'), isTrue);
        expect(InputValidator.isValidZipCode('33076'), isTrue);
        expect(InputValidator.isValidZipCode('00000'), isTrue);
        expect(InputValidator.isValidZipCode('99999'), isTrue);
      });

      test('rejects zip codes that are too short', () {
        expect(InputValidator.isValidZipCode('3307'), isFalse);
        expect(InputValidator.isValidZipCode('330'), isFalse);
        expect(InputValidator.isValidZipCode(''), isFalse);
      });

      test('rejects zip codes that are too long', () {
        expect(InputValidator.isValidZipCode('330711'), isFalse);
        expect(InputValidator.isValidZipCode('3307100'), isFalse);
      });

      test('rejects non-numeric zip codes', () {
        expect(InputValidator.isValidZipCode('abcde'), isFalse);
        expect(InputValidator.isValidZipCode('330a1'), isFalse);
        expect(InputValidator.isValidZipCode('33 71'), isFalse);
      });
    });

    group('isValidPrice', () {
      test('accepts valid prices', () {
        expect(InputValidator.isValidPrice('150.00'), isTrue);
        expect(InputValidator.isValidPrice('65'), isTrue);
        expect(InputValidator.isValidPrice('0'), isTrue);
        expect(InputValidator.isValidPrice('0.01'), isTrue);
        expect(InputValidator.isValidPrice('9999.99'), isTrue);
      });

      test('rejects non-numeric prices', () {
        expect(InputValidator.isValidPrice('abc'), isFalse);
        expect(InputValidator.isValidPrice(''), isFalse);
        expect(InputValidator.isValidPrice('12.34.56'), isFalse);
      });

      test('rejects negative prices', () {
        expect(InputValidator.isValidPrice('-50'), isFalse);
        expect(InputValidator.isValidPrice('-0.01'), isFalse);
      });
    });

    group('isValidFacilityName', () {
      test('accepts valid facility names', () {
        expect(InputValidator.isValidFacilityName('Public Storage'), isTrue);
        expect(InputValidator.isValidFacilityName('Extra Space - University Dr'), isTrue);
        expect(InputValidator.isValidFacilityName('A'), isTrue);
      });

      test('rejects empty or whitespace-only names', () {
        expect(InputValidator.isValidFacilityName(''), isFalse);
        expect(InputValidator.isValidFacilityName('   '), isFalse);
        expect(InputValidator.isValidFacilityName('\t\n'), isFalse);
      });
    });
  });

  group('CsvRowGenerator', () {
    test('generates correct CSV header', () {
      expect(CsvRowGenerator.header, equals('date,zip,facility,cost,revenue,spread,insurance_waived'));
    });

    test('generates correct CSV row', () {
      final row = CsvRowGenerator.generateRow(
        date: DateTime(2026, 1, 27),
        zipCode: '33071',
        facilityName: 'Public Storage',
        commercialPrice: 150.0,
        neighborRate: 65.0,
        spread: 98.0,
        hasInsuranceWaiver: false,
      );
      expect(row, equals('2026-01-27,33071,Public Storage,150.0,260.0,98.00,false'));
    });

    test('handles facility names with special characters', () {
      final row = CsvRowGenerator.generateRow(
        date: DateTime(2026, 1, 27),
        zipCode: '33076',
        facilityName: 'Extra Space - University Dr',
        commercialPrice: 175.0,
        neighborRate: 70.0,
        spread: 93.0,
        hasInsuranceWaiver: true,
      );
      expect(row.contains('Extra Space - University Dr'), isTrue);
      expect(row.endsWith('true'), isTrue);
    });

    test('formats spread to 2 decimal places', () {
      final row = CsvRowGenerator.generateRow(
        date: DateTime(2026, 1, 27),
        zipCode: '33071',
        facilityName: 'Test',
        commercialPrice: 150.0,
        neighborRate: 65.0,
        spread: 98.123456,
        hasInsuranceWaiver: false,
      );
      expect(row.contains('98.12'), isTrue);
    });
  });
}
